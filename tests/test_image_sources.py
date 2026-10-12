"""内置镜像源测试：源列表结构、候选解析（自动/固定/自定义）、逐源回退、可用性探测（不联网）。"""
import io
import json
import zipfile
from pathlib import Path

import pytest

from config.settings import SettingsManager
from mirror.image import BUILTIN_IMAGE_DEFS
from mirror.image_manager import (
    ImageManager, ImageManagerError, load_sources, source_url,
)

IMAGE_ID = "aosp-13-arm64"


def make_image_zip(android_version: int = 13) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("image.json", json.dumps({
            "id": f"aosp-{android_version}-arm64",
            "name": f"AOSP {android_version} (ARM64)",
            "android_version": android_version, "arch": "arm64-v8a",
            "kernel": "Image",
            "cmdline": "console=ttyAMA0 root=/dev/nvme0n1 rootwait rw",
            "drives": [{"file": "system.img", "format": "raw", "id": "system",
                        "base": "true"}],
        }))
        zf.writestr("Image", b"kernel")
        zf.writestr("system.img", b"system")
    return buf.getvalue()


class FakeResponse:
    """最小 urllib 响应替身：支持 _fetch_zip 的 headers/read/上下文协议。"""

    def __init__(self, data: bytes) -> None:
        self.headers = {"Content-Length": str(len(data))}
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._data) - self._pos
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def test_registry_has_two_china_and_two_global_sources():
    sources = load_sources()
    assert len(sources) >= 4
    china = [s for s in sources if s["region"] == "china"]
    global_ = [s for s in sources if s["region"] == "global"]
    assert len(china) >= 2 and len(global_) >= 2
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids)), "内置源 id 必须唯一"
    for src in sources:
        assert src["base_url"].startswith("https://"), src
    # 国内源排前（自动模式的尝试顺序）
    regions = [s["region"] for s in sources]
    assert regions == sorted(regions, key=lambda r: 0 if r == "china" else 1)


def test_registry_file_matches_code_expectations():
    data = json.loads((Path(__file__).resolve().parents[1] / "resource"
                       / "image_sources.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["sources"]) == 4


def test_source_url_joins_base_and_image():
    assert source_url("https://host/x/", IMAGE_ID) == f"https://host/x/{IMAGE_ID}.zip"
    assert source_url("https://host/x", IMAGE_ID) == f"https://host/x/{IMAGE_ID}.zip"


def test_resolve_auto_tries_all_sources_china_first(stararm_home):
    mgr = ImageManager(SettingsManager())
    candidates = mgr.resolve_candidates(IMAGE_ID)
    assert len(candidates) == len(load_sources())
    regions = [next(s["region"] for s in load_sources() if s["id"] == c[0])
               for c in candidates]
    assert regions[0] == "china" and regions[-1] == "global"
    assert all(c[2].endswith(f"/{IMAGE_ID}.zip") for c in candidates)


def test_resolve_pinned_source_uses_only_that_source(stararm_home):
    settings = SettingsManager()
    settings.update(image_source_id="github")
    mgr = ImageManager(settings)
    candidates = mgr.resolve_candidates(IMAGE_ID)
    assert [c[0] for c in candidates] == ["github"]


def test_resolve_unknown_id_falls_back_to_auto(stararm_home):
    settings = SettingsManager()
    settings.update(image_source_id="does-not-exist")
    mgr = ImageManager(settings)
    assert len(mgr.resolve_candidates(IMAGE_ID)) == len(load_sources())


def test_resolve_custom_requires_url(stararm_home):
    settings = SettingsManager()
    settings.update(image_source_id="custom", image_source="")
    mgr = ImageManager(settings)
    with pytest.raises(ImageManagerError) as excinfo:
        mgr.resolve_candidates(IMAGE_ID)
    assert excinfo.value.key == "err_no_image_source"


def test_resolve_custom_uses_single_url(stararm_home):
    settings = SettingsManager()
    settings.update(image_source_id="custom", image_source="https://mirror.local/img/")
    mgr = ImageManager(settings)
    candidates = mgr.resolve_candidates(IMAGE_ID)
    assert [c[0] for c in candidates] == ["custom"]
    assert candidates[0][2] == f"https://mirror.local/img/{IMAGE_ID}.zip"


def test_download_falls_back_to_next_source(stararm_home, monkeypatch):
    payload = make_image_zip()
    urls = []

    def fake_urlopen(request, timeout=None, *args, **kwargs):
        url = request.full_url
        urls.append(url)
        if len(urls) == 1:
            raise OSError("connection refused")
        return FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    mgr = ImageManager(SettingsManager())
    image = mgr.download_builtin(IMAGE_ID)
    assert image.is_ready
    assert len(urls) == 2, "第一个源失败后应回退到第二个源"
    assert urls[0] != urls[1]


def test_download_reports_every_failed_source(stararm_home, monkeypatch):
    def fake_urlopen(request, timeout=None, *args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    mgr = ImageManager(SettingsManager())
    with pytest.raises(ImageManagerError) as excinfo:
        mgr.download_builtin(IMAGE_ID)
    assert excinfo.value.key == "err_image_all_sources_failed"
    for src in load_sources():
        assert src["name"] in excinfo.value.detail, f"错误详情应包含 {src['name']}"


def test_download_with_pinned_source_only_hits_that_source(stararm_home, monkeypatch):
    settings = SettingsManager()
    settings.update(image_source_id="hf")
    urls = []

    def fake_urlopen(request, timeout=None, *args, **kwargs):
        urls.append(request.full_url)
        raise OSError("timeout")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    mgr = ImageManager(settings)
    with pytest.raises(ImageManagerError):
        mgr.download_builtin(IMAGE_ID)
    assert len(urls) == 1
    assert "huggingface.co" in urls[0]


def test_download_sets_timeout_and_user_agent(stararm_home, monkeypatch):
    """下载必须带超时与 UA（无超时会让不可达源卡住逐源回退）。"""
    seen = {}

    def fake_urlopen(request, timeout=None, *args, **kwargs):
        seen["timeout"] = timeout
        seen["ua"] = request.get_header("User-agent")
        raise OSError("stop here")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    mgr = ImageManager(SettingsManager())
    with pytest.raises(ImageManagerError):
        mgr.download_builtin(IMAGE_ID)
    assert seen["timeout"] and seen["timeout"] > 0
    assert seen["ua"]


def test_check_source_states(stararm_home, monkeypatch):
    mgr = ImageManager(SettingsManager())

    monkeypatch.setattr("mirror.image_manager._head", lambda url, timeout=8.0: (200, ""))
    state, detail = mgr.check_source("https://ok.example")
    assert state == "ok" and detail in [d["id"] for d in BUILTIN_IMAGE_DEFS]

    monkeypatch.setattr("mirror.image_manager._head", lambda url, timeout=8.0: (404, ""))
    state, detail = mgr.check_source("https://empty.example")
    assert state == "missing" and detail == "404"

    monkeypatch.setattr("mirror.image_manager._head",
                        lambda url, timeout=8.0: (None, "timed out"))
    state, _detail = mgr.check_source("https://dead.example")
    assert state == "error"


def test_check_source_accepts_explicit_image_id(stararm_home, monkeypatch):
    seen = []

    def fake_head(url, timeout=8.0):
        seen.append(url)
        return (200, "")

    monkeypatch.setattr("mirror.image_manager._head", fake_head)
    mgr = ImageManager(SettingsManager())
    state, detail = mgr.check_source("https://ok.example", IMAGE_ID)
    assert state == "ok" and detail == IMAGE_ID
    assert seen == [f"https://ok.example/{IMAGE_ID}.zip"]
