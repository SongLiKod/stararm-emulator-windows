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
# （内核 ikconfig 无 virtio 驱动 → NVMe 根盘 + rootwait；
#  printk.devkmsg=on 解除 userspace 日志 ratelimit，供排查 apexd/init 卡点）
DEFAULT_CMDLINE = (
    "console=ttyAMA0,38400 root=/dev/nvme0n1 rootwait rw printk.devkmsg=on "
    "androidboot.hardware=stararm "
    "androidboot.selinux=permissive androidboot.vbmeta.device_state=unlocked "
    "androidboot.verifiedbootstate=orange"
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
