"""镜像管理测试：内置定义（Android 11-15）、导入导出、aarch64 校验、禁止 X86。"""
import json
import zipfile

import pytest

from config.settings import SettingsManager
from mirror.image import BUILTIN_IMAGE_DEFS
from mirror.image_manager import ImageManager, ImageManagerError


def make_image_dir(base, android_version=13, arch="arm64-v8a"):
    d = base / f"aosp-{android_version}-arm64"
    d.mkdir(parents=True)
    (d / "Image").write_bytes(b"kernel")
    (d / "system.img").write_bytes(b"system")
    (d / "image.json").write_text(json.dumps({
        "id": d.name, "name": f"AOSP {android_version} (ARM64)",
        "android_version": android_version, "arch": arch,
        "kernel": "Image",
        "cmdline": "console=ttyAMA0 root=/dev/vda1 rw",
        "drives": [{"file": "system.img", "format": "raw", "id": "system",
                    "base": "true"}],
    }), encoding="utf-8")
    return d


def test_builtin_defs_cover_android_11_to_15():
    versions = sorted(d["android_version"] for d in BUILTIN_IMAGE_DEFS)
    assert versions == [11, 12, 13, 14, 15]


def test_list_images_includes_builtin_defs(stararm_home, tmp_path):
    make_image_dir(tmp_path)
    settings = SettingsManager()
    mgr = ImageManager(settings)
    # 将镜像放入用户镜像目录
    import shutil
    shutil.copytree(tmp_path / "aosp-13-arm64", stararm_home / "mirror" / "images" / "aosp-13-arm64")
    ids = [i.id for i in mgr.list_images()]
    for d in BUILTIN_IMAGE_DEFS:
        assert d["id"] in ids


def test_import_image_dir_validates_arm64(stararm_home, tmp_path):
    settings = SettingsManager()
    mgr = ImageManager(settings)
    src = make_image_dir(tmp_path, android_version=15)
    img = mgr.import_image(src)
    assert img.android_version == 15
    assert img.is_ready
    # 导入后可被列出
    assert mgr.get(img.id) is not None


def test_import_image_rejects_x86(stararm_home, tmp_path):
    settings = SettingsManager()
    mgr = ImageManager(settings)
    src = make_image_dir(tmp_path, android_version=13, arch="x86_64")
    with pytest.raises(ImageManagerError) as excinfo:
        mgr.import_image(src)
    assert excinfo.value.key == "err_image_not_arm64"


def test_import_image_from_zip(stararm_home, tmp_path):
    settings = SettingsManager()
    mgr = ImageManager(settings)
    src = make_image_dir(tmp_path, android_version=14)
    zip_path = tmp_path / "aosp-14.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src.parent))
    img = mgr.import_image(zip_path)
    assert img.id == "aosp-14-arm64"
    assert (stararm_home / "mirror" / "images" / "aosp-14-arm64" / "image.json").is_file()


def test_import_missing_manifest_raises(stararm_home, tmp_path):
    settings = SettingsManager()
    mgr = ImageManager(settings)
    d = tmp_path / "no-manifest"
    d.mkdir()
    (d / "Image").write_bytes(b"k")
    with pytest.raises(ImageManagerError) as excinfo:
        mgr.import_image(d)
    assert excinfo.value.key == "err_image_manifest_missing"


def test_import_missing_files_raises(stararm_home, tmp_path):
    settings = SettingsManager()
    mgr = ImageManager(settings)
    d = tmp_path / "no-files"
    d.mkdir()
    (d / "image.json").write_text(json.dumps({
        "id": "bad", "arch": "arm64-v8a", "kernel": "Image",
        "drives": [{"file": "system.img"}],
    }), encoding="utf-8")
    with pytest.raises(ImageManagerError) as excinfo:
        mgr.import_image(d)
    assert excinfo.value.key == "err_image_files_missing"


def test_get_ready_requires_files(stararm_home):
    settings = SettingsManager()
    mgr = ImageManager(settings)
    # 内置镜像未就绪（无文件）
    with pytest.raises(ImageManagerError) as excinfo:
        mgr.get_ready("aosp-13-arm64")
    assert excinfo.value.key == "err_image_not_ready"


def test_download_without_source_raises(stararm_home):
    settings = SettingsManager()
    mgr = ImageManager(settings)
    with pytest.raises(ImageManagerError) as excinfo:
        mgr.download_builtin("aosp-13-arm64")
    assert excinfo.value.key == "err_no_image_source"


def test_export_image(stararm_home, tmp_path):
    settings = SettingsManager()
    mgr = ImageManager(settings)
    src = make_image_dir(tmp_path, android_version=12)
    img = mgr.import_image(src)
    out = tmp_path / "export.zip"
    mgr.export_image(img.id, out)
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        assert "image.json" in zf.namelist() or any(
            n.endswith("image.json") for n in zf.namelist())
