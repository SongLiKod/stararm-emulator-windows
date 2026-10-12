"""镜像管理：内置镜像（Android 11-15）、用户自定义导入、镜像导出、镜像下载。

镜像存储位置：
1. 仓库/部署包内：mirror/images/（内置随包镜像，只读）
2. 用户数据目录：STARARM_HOME/mirror/images/（下载与导入的镜像）

镜像下载源：resource/image_sources.json 内置多条（国内 2 + 海外 2），
下载按设置逐源尝试并自动回退；也可用全局设置里的自定义 URL。
"""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import urllib.error
import urllib.request

from config import paths
from config.settings import SettingsManager
from log.logger import get_logger
from mirror.image import AndroidImage, ImageManifest, BUILTIN_IMAGE_DEFS, load_manifest

# 下载超时（连接/读取均受控，避免个别源长时间无响应阻塞逐源回退）
DOWNLOAD_TIMEOUT = 20.0
HEAD_TIMEOUT = 8.0
DOWNLOAD_UA = "StarARM-ImageFetcher/1.0 (+https://github.com/SongLiKod/stararm-emulator-windows)"

# 资源文件缺失/损坏时的兜底内置源（与 resource/image_sources.json 保持一致）
BUILTIN_SOURCES: List[Dict] = [
    {"id": "ghfast", "region": "china", "name": "ghfast.top",
     "base_url": "https://ghfast.top/https://github.com/SongLiKod/stararm-emulator-windows"
                 "/releases/download/images"},
    {"id": "hfmirror", "region": "china", "name": "hf-mirror.com",
     "base_url": "https://hf-mirror.com/datasets/SongLiKod/stararm-images/resolve/main"},
    {"id": "github", "region": "global", "name": "GitHub Releases",
     "base_url": "https://github.com/SongLiKod/stararm-emulator-windows/releases/download/images"},
    {"id": "hf", "region": "global", "name": "Hugging Face",
     "base_url": "https://huggingface.co/datasets/SongLiKod/stararm-images/resolve/main"},
]


def source_url(base_url: str, image_id: str) -> str:
    return f"{base_url.rstrip('/')}/{image_id}.zip"


def load_sources() -> List[Dict]:
    """读取内置镜像源列表（国内源排前；文件缺失/非法时用代码内置兜底）。"""
    try:
        data = json.loads((paths.resource_dir() / "image_sources.json").read_text(encoding="utf-8"))
        raw = data.get("sources") if isinstance(data, dict) else None
    except (OSError, ValueError):
        raw = None
    sources: List[Dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        base = str(item.get("base_url", "")).strip()
        if not base.startswith(("http://", "https://")):
            continue
        sources.append({
            "id": str(item.get("id", "")).strip(),
            "region": str(item.get("region", "global")).strip() or "global",
            "name": str(item.get("name", base)).strip() or base,
            "base_url": base,
            "homepage": str(item.get("homepage", "")).strip(),
        })
    if not any(s["id"] for s in sources):
        sources = [dict(s) for s in BUILTIN_SOURCES]
    sources.sort(key=lambda s: 0 if s.get("region") == "china" else 1)
    return sources


def _head(url: str, timeout: float = HEAD_TIMEOUT) -> Tuple[Optional[int], str]:
    """探测源可用性：优先 HEAD，网络失败时回退 Range GET（部分代理不支持 HEAD）。"""
    last_error = "unreachable"
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": DOWNLOAD_UA})
        if method == "GET":
            request.add_header("Range", "bytes=0-0")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), ""
        except urllib.error.HTTPError as exc:
            return int(exc.code), ""
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)[:160]
    return None, last_error


class ImageManagerError(RuntimeError):
    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(detail)
        self.key = key
        self.detail = detail


class ImageManager:
    def __init__(self, settings: SettingsManager) -> None:
        self._settings = settings

    # ------------------------------------------------------------- storage
    def builtin_dir(self) -> Path:
        """内置镜像目录（开发环境为仓库 mirror/images，打包后为 exe 同级 mirror/images）。"""
        import sys
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "mirror" / "images"
        return Path(__file__).resolve().parent / "images"

    def user_dir(self) -> Path:
        return paths.images_dir()

    def all_dirs(self) -> List[Path]:
        return [self.user_dir(), self.builtin_dir()]

    # ------------------------------------------------------------- listing
    def list_images(self) -> List[AndroidImage]:
        """列出全部镜像：本地镜像 + 内置镜像定义（未就绪的内置项 available=False）。"""
        found: Dict[str, AndroidImage] = {}
        for base in self.all_dirs():
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_dir():
                    continue
                m = load_manifest(child)
                if m:
                    found[m.id] = AndroidImage(m, child, available=True)
        images: List[AndroidImage] = []
        for m in BUILTIN_IMAGE_DEFS:
            img = found.pop(m["id"], None)
            if img is None:
                manifest = ImageManifest(
                    id=m["id"], name=m["name"], android_version=m["android_version"],
                )
                images.append(AndroidImage(manifest, self.user_dir() / m["id"], available=False))
            else:
                images.append(img)
        for img in found.values():
            images.append(img)
        images.sort(key=lambda i: (0 if not i.available else 1, i.manifest.android_version))
        return images

    def get(self, image_id: str) -> Optional[AndroidImage]:
        for img in self.list_images():
            if img.id == image_id:
                return img
        return None

    def get_ready(self, image_id: str) -> AndroidImage:
        img = self.get(image_id)
        if img is None:
            raise ImageManagerError("err_image_not_found", image_id)
        if not img.is_ready:
            raise ImageManagerError(
                "err_image_not_ready",
                ", ".join(img.missing_files()),
            )
        return img

    # ------------------------------------------------------------- import
    def import_image(self, source: Path) -> AndroidImage:
        """导入自定义镜像：支持镜像目录或 zip 包；强制校验 ARM64（aarch64）架构。

        禁止导入 X86/X86_64 镜像 —— 本产品纯 ARM64 原生执行，不依赖任何转译组件。
        """
        source = Path(source)
        with tempfile.TemporaryDirectory(prefix="stararm-img-") as tmp:
            work = Path(tmp)
            if source.is_file() and source.suffix.lower() == ".zip":
                extract_root = work / "extract"
                extract_root.mkdir()
                with zipfile.ZipFile(source) as zf:
                    zf.extractall(extract_root)
                # 定位含 image.json 的目录（zip 可能有一层包裹目录）
                candidates = [d for d in extract_root.rglob("image.json")]
                if not candidates:
                    raise ImageManagerError("err_image_manifest_missing", str(source))
                src_dir = candidates[0].parent
            elif source.is_dir():
                src_dir = source
            else:
                raise ImageManagerError("err_image_source_invalid", str(source))

            manifest = load_manifest(src_dir)
            if manifest is None:
                raise ImageManagerError("err_image_manifest_missing", str(source))
            if not ImageManifest.is_arm64(manifest.arch):
                raise ImageManagerError("err_image_not_arm64", manifest.arch)

            missing = AndroidImage(manifest, src_dir).missing_files()
            if missing:
                raise ImageManagerError("err_image_files_missing", ", ".join(missing))

            dest = self.user_dir() / manifest.id
            index = 1
            while dest.exists():
                index += 1
                dest = self.user_dir() / f"{manifest.id}-{index}"
            manifest.id = dest.name
            shutil.copytree(src_dir, dest)
            (dest / "image.json").write_text(
                __import__("json").dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result = AndroidImage(manifest, dest, available=True)
            get_logger().system("log_image_imported", id=manifest.id)
            return result

    # ------------------------------------------------------------- export
    def export_image(self, image_id: str, zip_path: Path) -> Path:
        """导出镜像为 zip 包（镜像导出）。"""
        img = self.get_ready(image_id)
        zip_path = Path(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(img.directory.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(img.directory.parent))
        get_logger().system("log_image_exported", id=image_id, path=str(zip_path))
        return zip_path

    # ------------------------------------------------------------- sources
    def sources(self) -> List[Dict]:
        """内置镜像源列表（来自 resource/image_sources.json，国内源排前）。"""
        return load_sources()

    def resolve_candidates(self, image_id: str) -> List[Tuple[str, str, str]]:
        """解析候选下载地址 (source_id, name, url)。

        设置 image_source_id：
        - 空 / "auto"：全部内置源依次尝试（国内优先）
        - "custom"：仅用 image_source 自定义 URL（未填则报 err_no_image_source）
        - 其他：仅用指定内置源（id 不存在时回退自动）
        """
        setting = self._settings.get()
        chosen = (getattr(setting, "image_source_id", "") or "auto").strip() or "auto"
        custom = (setting.image_source or "").strip()
        registry = load_sources()
        if chosen == "custom":
            if not custom:
                raise ImageManagerError("err_no_image_source", "")
            return [("custom", custom, source_url(custom, image_id))]
        if chosen != "auto":
            for src in registry:
                if src.get("id") == chosen:
                    return [(src["id"], src["name"], source_url(src["base_url"], image_id))]
        return [(src["id"], src["name"], source_url(src["base_url"], image_id))
                for src in registry]

    def check_source(self, base_url: str,
                     image_id: Optional[str] = None) -> Tuple[str, str]:
        """检测镜像源可用性，返回 (state, detail)：ok=有镜像 / missing=源可达无此镜像 / error=无法连接。"""
        probes = [image_id] if image_id else [d["id"] for d in BUILTIN_IMAGE_DEFS]
        last_error = ""
        for probe in probes:
            code, err = _head(source_url(base_url, probe))
            if err:
                return "error", err
            if code == 200:
                return "ok", probe
            if code is not None:
                return "missing", str(code)
        return "error", last_error or "unreachable"

    # ------------------------------------------------------------- download
    def download_builtin(self, image_id: str, progress: Optional[Callable[[int, int], None]] = None) -> AndroidImage:
        """按当前设置的镜像源下载内置镜像：逐源尝试并自动回退，全部失败给出逐源原因。"""
        candidates = self.resolve_candidates(image_id)
        errors: List[str] = []
        for source_id, name, url in candidates:
            try:
                image = self._fetch_zip(url, progress)
            except ImageManagerError as exc:
                errors.append(f"{name}: {exc.detail or exc.key}")
                continue
            get_logger().system("log_image_downloaded", id=image_id, source=source_id)
            return image
        raise ImageManagerError("err_image_all_sources_failed", "; ".join(errors)[:400])

    def _fetch_zip(self, url: str, progress: Optional[Callable[[int, int], None]] = None) -> AndroidImage:
        """按 URL 下载镜像 zip（带超时，避免个别源长时间无响应阻塞逐源回退）。"""
        with tempfile.TemporaryDirectory(prefix="stararm-dl-") as tmp:
            zip_file = Path(tmp) / "image.zip"
            try:
                request = urllib.request.Request(url, headers={"User-Agent": DOWNLOAD_UA})
                with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
                    total = int(response.headers.get("Content-Length") or 0)
                    done = 0
                    with open(zip_file, "wb") as out:
                        while True:
                            chunk = response.read(1 << 16)
                            if not chunk:
                                break
                            out.write(chunk)
                            done += len(chunk)
                            if progress:
                                progress(done, total)
            except Exception as exc:
                raise ImageManagerError("err_image_download_failed", str(exc)[:200]) from exc
            return self.import_image(zip_file)
