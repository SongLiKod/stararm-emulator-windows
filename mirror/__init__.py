"""ARM64 安卓镜像层：镜像存储、镜像管理。

内置标准 AOSP ARM64 镜像（Android 11-15，无魔改、无转译、纯原生 ARM 执行）；
支持用户自定义导入镜像与镜像导出、镜像替换。
"""
from mirror.image import AndroidImage, ImageManifest, BUILTIN_IMAGE_DEFS
from mirror.image_manager import ImageManager

__all__ = ["AndroidImage", "ImageManifest", "BUILTIN_IMAGE_DEFS", "ImageManager"]
