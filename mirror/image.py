"""镜像模型与内置镜像定义（Android 11-15 标准 AOSP ARM64）。

镜像目录结构（每套镜像一个子目录，含 image.json 清单）：
    <id>/image.json      清单（版本、架构、内核、启动参数、磁盘镜像列表）
    <id>/Image           内核
    <id>/ramdisk.img     ramdisk（可选）
    <id>/system.img      系统镜像（只读共享，实例用 qcow2 覆盖层写入）
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# 内置标准镜像定义（实际镜像文件通过设置中的“镜像源”下载或手动导入，见 image_manager）
BUILTIN_IMAGE_DEFS: List[Dict] = [
    {"id": f"aosp-{v}-arm64", "android_version": v, "name": f"AOSP {v} (ARM64)"}
    for v in (11, 12, 13, 14, 15)
]


@dataclass
class ImageManifest:
    id: str = ""
    name: str = ""
    android_version: int = 13
    arch: str = "arm64-v8a"          # 必须为 ARM64 架构，禁止导入 X86 镜像
    kernel: str = "Image"
    ramdisk: str = ""                # 可选
    cmdline: str = "console=ttyAMA0,38400 root=/dev/vda1 rw androidboot.hardware=stararm"
    dtb: str = ""                    # 可选
    drives: List[Dict[str, str]] = field(default_factory=lambda: [
        {"file": "system.img", "format": "raw", "id": "system", "base": "true"}
    ])

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "android_version": self.android_version,
            "arch": self.arch, "kernel": self.kernel, "ramdisk": self.ramdisk,
            "cmdline": self.cmdline, "dtb": self.dtb, "drives": self.drives,
        }

    @staticmethod
    def from_dict(data: dict) -> "ImageManifest":
        m = ImageManifest()
        m.id = str(data.get("id", ""))
        m.name = str(data.get("name", ""))
        try:
            m.android_version = int(data.get("android_version", 13))
        except (TypeError, ValueError):
            m.android_version = 13
        m.arch = str(data.get("arch", "arm64-v8a"))
        m.kernel = str(data.get("kernel", "Image"))
        m.ramdisk = str(data.get("ramdisk", ""))
        m.cmdline = str(data.get("cmdline", ""))
        m.dtb = str(data.get("dtb", ""))
        drives = data.get("drives", [])
        m.drives = [d for d in drives if isinstance(d, dict) and d.get("file")]
        return m

    @staticmethod
    def is_arm64(arch: str) -> bool:
        a = (arch or "").lower()
        return "arm64" in a or "aarch64" in a


@dataclass
class AndroidImage:
    manifest: ImageManifest
    directory: Path
    available: bool = True

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def android_version(self) -> int:
        return self.manifest.android_version

    @property
    def name(self) -> str:
        return self.manifest.name

    def file_path(self, name: str) -> Path:
        return self.directory / name

    def base_drive(self) -> Optional[Dict[str, str]]:
        """实例覆盖层（qcow2 overlay）的 backing file 镜像盘。"""
        for d in self.manifest.drives:
            if str(d.get("base", "")).lower() in ("1", "true", "yes"):
                return d
        return self.manifest.drives[0] if self.manifest.drives else None

    def missing_files(self) -> List[str]:
        missing = []
        if not self.file_path(self.manifest.kernel).is_file():
            missing.append(self.manifest.kernel)
        if self.manifest.ramdisk and not self.file_path(self.manifest.ramdisk).is_file():
            missing.append(self.manifest.ramdisk)
        for d in self.manifest.drives:
            if not self.file_path(d["file"]).is_file():
                missing.append(d["file"])
        if self.manifest.dtb and not self.file_path(self.manifest.dtb).is_file():
            missing.append(self.manifest.dtb)
        return missing

    @property
    def is_ready(self) -> bool:
        return self.available and not self.missing_files()


def load_manifest(directory: Path) -> Optional[ImageManifest]:
    """从镜像目录读取 image.json 清单。"""
    manifest_file = directory / "image.json"
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        m = ImageManifest.from_dict(data)
        if not m.id:
            m.id = directory.name
        if not m.name:
            m.name = m.id
        return m
    except (OSError, ValueError):
        return None
