"""QEMU 启动故障分类：将 QEMU stderr 归类为中文/英文双语提示词条。"""

ERROR_UNKNOWN = "err_unknown"
ERROR_VIRTUALIZATION = "err_virtualization"
ERROR_GRAPHICS = "err_graphics"
ERROR_PORT = "err_port"
ERROR_BRIDGE = "err_bridge"
ERROR_DISK = "err_disk"
ERROR_IMAGE = "err_image"
ERROR_NOT_FOUND = "err_qemu_not_found"


def classify_qemu_error(stderr: str) -> str:
    """根据 QEMU 输出分类错误，返回 i18n 词条 key（启动故障中文提示）。"""
    s = (stderr or "").lower()
    if "whpx" in s or "hypervisor" in s or "virtualization" in s or "wHPX" in (stderr or ""):
        return ERROR_VIRTUALIZATION
    if "egl" in s or "virgl" in s or "venus" in s or "opengl" in s or "gpu" in s:
        return ERROR_GRAPHICS
    if "address already in use" in s or "could not set up" in s and "port" in s or "port" in s and "listen" in s:
        return ERROR_PORT
    if "tap" in s or "bridge" in s or "network" in s:
        return ERROR_BRIDGE
    if "disk" in s or "no space" in s or "qcow2" in s or "overlay" in s:
        return ERROR_DISK
    if "could not open" in s or "image" in s or "kernel" in s or "ramdisk" in s:
        return ERROR_IMAGE
    return ERROR_UNKNOWN


def is_graphics_error(error_key: str, stderr: str = "") -> bool:
    if error_key == ERROR_GRAPHICS:
        return True
    s = (stderr or "").lower()
    return "egl" in s or "virgl" in s or "venus" in s
