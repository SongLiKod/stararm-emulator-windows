"""镜像管理：内置镜像（Android 11-15）、用户自定义导入、镜像导出、镜像下载。

镜像存储位置：
1. 仓库/部署包内：mirror/images/（内置随包镜像，只读）
2. 用户数据目录：STARARM_HOME/mirror/images/（下载与导入的镜像）
"""
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import urllib.request

from config import paths
from config.settings import SettingsManager
from log.logger import get_logger
from mirror.image import AndroidImage, ImageManifest, BUILTIN_IMAGE_DEFS, load_manifest


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

    # ------------------------------------------------------------- download
    def download_builtin(self, image_id: str, progress: Optional[Callable[[int, int], None]] = None) -> AndroidImage:
        """从全局设置中的镜像源下载内置镜像（内置标准 AOSP ARM64 镜像获取通道）。"""
        source = (self._settings.get().image_source or "").strip()
        if not source:
            raise ImageManagerError("err_no_image_source", "")
        url = f"{source.rstrip('/')}/{image_id}.zip"
        with tempfile.TemporaryDirectory(prefix="stararm-dl-") as tmp:
            zip_file = Path(tmp) / "image.zip"
            try:
                if progress:
                    def hook(blocks: int, block_size: int, total: int) -> None:
                        progress(blocks * block_size, total)
                    urllib.request.urlretrieve(url, zip_file, reporthook=hook)
                else:
                    urllib.request.urlretrieve(url, zip_file)
            except Exception as exc:
                raise ImageManagerError("err_image_download_failed", str(exc)[:200]) from exc
            return self.import_image(zip_file)
