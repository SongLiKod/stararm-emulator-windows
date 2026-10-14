#!/usr/bin/env python3
"""生成 image.json 并打包 StarARM 镜像 zip（含 2GiB 发布门禁）。

用法:
  python3 build/image/mkimage.py --dir dist --id aosp-14-arm64 --version 14 \
      --name "AOSP 14 (ARM64)" --out dist/aosp-14-arm64.zip [--max-gb 1.9]
退出码: 0 成功; 2 缺文件; 3 超过 --max-gb 门禁（zip 仍会写出，供诊断）
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

# 与 core/qemu_manager.py build_args 契约一致的默认启动参数
# （内核内置配置无 virtio/DRM → NVMe 根盘 + rootwait；
#  printk.devkmsg=on 解除 userspace 日志 ratelimit，供排查 apexd/init 卡点；
#  图形属性基线 = google/android-cuttlefish qemu_manager.cpp ConfigureGraphics，
#  /dev/dri 由 vendor_dlkm 的 vkms.ko 提供（init.stararm.rc post-fs modprobe）。
#  实证链：712eb10 无属性→EGL not found；fd3746a egl=mesa 无 /dev/dri→0 configs；
#  7e16fa6 vkms 已加载（[drm] Initialized vkms）+ minigbm allocator 正常开 /dev/dri/card0、
#  ranchu 已探测 vkms uevent，但 mesa 仍 0 configs → mesa(android) 需 virgl/venus Gallium
#  驱动（CF DrmVirgl=宿主 virgl），纯软 vkms 无 3D 驱动 → mesa 死路。
#  本轮改 egl=angle（CF GuestSwiftshader 同款：ANGLE GLES-on-Vulkan + 客户机原生
#  swiftshader/lavapipe ICD，无宿主依赖）；ICD 是否在镜像内由 init.stararm.rc
#  串口探针核实（ls /system/etc/vulkan/icd.d 等 → /dev/console）。
#  run 8fa65e9 探针定案：镜像无 icd.d json、system 无 egl 目录、无 swiftshader/apex ——
#  但 /vendor/lib64/hw/vulkan.pastel.so（28.9MB，GuestSwiftshader 纯软 ICD）在镜像内，
#  仅缺 json 暴露。assemble.sh 注入 pastel json + 自建 libvk_swiftshader.so（34.7MB，
#  NDK r26 自建）双 ICD；cmdline 补 vulkan=pastel 与 CF GuestSwiftshader 配置对齐。
#  run 41e94a7 实证：双 ICD 生效（EGL 错误全消失），SF 卡 "HWC did not hotplug" ——
#  hwc3 读 ro.vendor.hwcomposer.*（本镜像缺 CF 的 init_graphics.vendor.rc 映射 → 走
#  GuestFrameComposer 宿主路径）；且 mode=client 的 ClientFrameComposer 硬依赖
#  DrmClient，DrmClient 只认 virtio-gpu（vkms 被拒）。定案 mode=noop + finder=noop：
#  NoOpFrameComposer 零依赖 + 720x1280 占位显示器 → hotplug → SF ANGLE GL 合成。
DEFAULT_CMDLINE = (
    "console=ttyAMA0,38400 root=/dev/nvme0n1 rootwait rw printk.devkmsg=on "
    "androidboot.hardware=stararm "
    "androidboot.selinux=permissive androidboot.vbmeta.device_state=unlocked "
    "androidboot.verifiedbootstate=orange "
    "androidboot.hardware.gralloc=minigbm "
    "androidboot.hardware.hwcomposer=noop "
    "androidboot.hardware.hwcomposer.mode=noop "
    "androidboot.hardware.hwcomposer.display_finder_mode=noop "
    "androidboot.hardware.egl=angle "
    "androidboot.hardware.vulkan=pastel "
    "androidboot.opengles.version=196608 "
    "androidboot.cpuvulkan.version=0"
)


def build_manifest(args: argparse.Namespace) -> dict:
    return {
        "id": args.id,
        "name": args.name,
        "android_version": args.version,
        "arch": "arm64-v8a",
        "kernel": "Image",
        "ramdisk": "",
        "cmdline": args.cmdline,
        "dtb": "",
        "drives": [
            {"file": "system.img", "format": "raw", "id": "system", "base": "true"}
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Pack StarARM image zip")
    p.add_argument("--dir", required=True, help="含 Image 与 system.img 的目录")
    p.add_argument("--id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--version", required=True, type=int)
    p.add_argument("--cmdline", default=DEFAULT_CMDLINE)
    p.add_argument("--out", required=True, help="输出 zip 路径")
    p.add_argument("--max-gb", type=float, default=1.9,
                   help="发布门禁（GB, zip 体积），0 表示不检查")
    a = p.parse_args()

    d = Path(a.dir)
    missing = [f for f in ("Image", "system.img") if not (d / f).is_file()]
    if missing:
        print(f"[mkimage] 缺少文件: {', '.join(missing)}（先运行 assemble）", file=sys.stderr)
        return 2

    manifest = build_manifest(a)
    (d / "image.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[mkimage] 打包 {out.name} ...", flush=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in ("image.json", "Image", "system.img"):
            zf.write(d / f, f)

    size = out.stat().st_size
    print(f"[mkimage] {out}: {size / 1024 / 1024:.1f} MB")
    for f in ("Image", "system.img"):
        print(f"[mkimage]   {f}: {(d / f).stat().st_size / 1024 / 1024:.1f} MB")

    if a.max_gb > 0 and size > a.max_gb * 1024 ** 3:
        print(f"[mkimage] 超过发布门禁 {a.max_gb} GB（GitHub Release 单文件上限 2GiB）；"
              f"请增大 PRUNE 裁剪后重建", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
