#!/usr/bin/env bash
# 把 Cuttlefish/AOSP 的 super.img + boot/init_boot/vendor_boot 组装成 StarARM 约定的单分区镜像：
#   staging 根分区 = init_boot 通用 ramdisk(/init 等) + vendor ramdisk + system/system_ext/vendor/product/odm 合并树
#   /data 由实例覆盖盘（qcow2 → /dev/vda2）提供，fstab.stararm 负责首启格式化挂载
# 依赖: otatools(lpunpack/simg2img/mkuserimg_mke2fs/unpack_bootimg), e2fsprogs, cpio, unzip, sudo(loop mount)
set -euo pipefail

WORK="${WORK:-.work}"
OUT="${OUT:-dist}"
IMG_ZIP="${IMG_ZIP:-}"
OTATOOLS_ZIP="${OTATOOLS_ZIP:-}"
PRUNE="${PRUNE:-}"
STAGING="$WORK/staging"
TOOLBIN="$WORK/otatools/bin"

log() { echo "[assemble] $*"; }
die() { echo "[assemble] ERROR: $*" >&2; exit 1; }

[ -n "$IMG_ZIP" ] && [ -f "$IMG_ZIP" ] || die "IMG_ZIP 未设置或不存在: '$IMG_ZIP'"
[ -n "$OTATOOLS_ZIP" ] && [ -f "$OTATOOLS_ZIP" ] || die "OTATOOLS_ZIP 未设置或不存在: '$OTATOOLS_ZIP'"

# 挂载 loop 分区需要 root：非 root 时用免密 sudo 重入自身
if [ "$(id -u)" != "0" ]; then
  command -v sudo >/dev/null || die "需要 root 权限（无 sudo）"
  sudo -n true 2>/dev/null || die "需要免密 sudo"
  exec sudo -E env WORK="$WORK" OUT="$OUT" IMG_ZIP="$IMG_ZIP" \
    OTATOOLS_ZIP="$OTATOOLS_ZIP" PRUNE="$PRUNE" bash "$0" "$@"
fi

rm -rf "$WORK/images" "$WORK/parts" "$WORK/mnt" "$STAGING"
mkdir -p "$WORK/images" "$WORK/parts" "$STAGING" "$OUT"

# ---- 1. 解压工具与镜像 ----
if [ ! -x "$TOOLBIN/lpunpack" ]; then
  log "解压 otatools"
  mkdir -p "$WORK/otatools"
  unzip -qo "$OTATOOLS_ZIP" -d "$WORK/otatools"
fi
export PATH="$TOOLBIN:$PATH"
export LD_LIBRARY_PATH="$WORK/otatools/lib64:${LD_LIBRARY_PATH:-}"
for t in lpunpack simg2img mkuserimg_mke2fs unpack_bootimg; do
  [ -x "$TOOLBIN/$t" ] || die "缺少工具 $t"
done

log "解压镜像包 $(basename "$IMG_ZIP")"
unzip -qo "$IMG_ZIP" -d "$WORK/images"
for f in boot.img init_boot.img super.img vendor_boot.img; do
  [ -f "$WORK/images/$f" ] || die "镜像包缺少 $f（确认 target 是完整设备构建，如 aosp_cf_arm64_phone-userdebug）"
done

# ---- 2. 拆 super（稀疏 → raw → 逻辑分区）----
log "拆分 super.img"
if ! simg2img "$WORK/images/super.img" "$WORK/super.raw" 2>/dev/null; then
  cp "$WORK/images/super.img" "$WORK/super.raw"
fi
lpunpack "$WORK/super.raw" "$WORK/parts" || die "lpunpack 失败"
rm -f "$WORK/super.raw" "$WORK/images/super.img"

# ---- 3. 各逻辑分区 → 合并根（自动识别是否带 <name>/ 前缀布局）----
mount_copy() { # part_name
  local name="$1" raw="$WORK/parts/$1.img" mnt="$WORK/mnt" sparse="$WORK/parts/$1.sparse"
  [ -f "$raw" ] || return 0
  rm -f "$sparse"
  simg2img "$raw" "$sparse" 2>/dev/null || cp "$raw" "$sparse"
  rm -f "$raw"
  rm -rf "$mnt"; mkdir -p "$mnt"
  mount -o ro,loop "$sparse" "$mnt"
  rm -f "$sparse"
  if [ -d "$mnt/$name" ]; then
    log "  $name: 带 $name/ 前缀布局"
    rsync -a "$mnt/" "$STAGING/"
  else
    log "  $name: 内容布局 → /$name"
    mkdir -p "$STAGING/$name"
    rsync -a "$mnt/" "$STAGING/$name/"
  fi
  umount "$mnt"
  rm -rf "$mnt"
}

for part in system system_ext vendor product odm system_dlkm vendor_dlkm odm_dlkm; do
  mount_copy "$part"
done

# ---- 4. ramdisk(init_boot 通用 + vendor_boot 厂商) 合入根 ----
extract_ramdisk() { # boot_img outdir → 打印解包目录
  local img="$1" out="$2"
  rm -rf "$out"; mkdir -p "$out"
  unpack_bootimg --boot_img "$img" --out "$out" >/dev/null
  local rd
  rd=$(find "$out" -maxdepth 2 -name '*ramdisk*' -type f | head -n1 || true)
  [ -n "$rd" ] || die "$img 未找到 ramdisk（输出: $(ls "$out" | tr '\n' ' ')）"
  local tmp="$out/rd"; rm -rf "$tmp"; mkdir -p "$tmp"
  if gzip -t "$rd" 2>/dev/null; then
    (cd "$tmp" && gzip -dc "$rd" | cpio -idmu --quiet)
  elif zstd -t "$rd" 2>/dev/null; then
    (cd "$tmp" && zstd -dc "$rd" | cpio -idmu --quiet)
  else
    (cd "$tmp" && cpio -idmu --quiet < "$rd")
  fi
  echo "$tmp"
}

log "合入 init_boot ramdisk"
RD_SYS=$(extract_ramdisk "$WORK/images/init_boot.img" "$WORK/rd_init")
rsync -a --ignore-existing "$RD_SYS/" "$STAGING/"

log "合入 vendor_boot ramdisk"
if find "$WORK/images/vendor_boot.img" -size +0c | grep -q .; then
  RD_VND=$(extract_ramdisk "$WORK/images/vendor_boot.img" "$WORK/rd_vendor" || true)
  if [ -n "${RD_VND:-}" ] && [ -d "$RD_VND" ]; then
    rsync -a --ignore-existing "$RD_VND/" "$STAGING/"
  fi
fi

# ---- 5. 内核 ----
unpack_bootimg --boot_img "$WORK/images/boot.img" --out "$WORK/boot" >/dev/null
[ -f "$WORK/boot/kernel" ] || die "boot.img 未提取到 kernel"
cp "$WORK/boot/kernel" "$OUT/Image"
log "kernel → $OUT/Image ($(du -h "$OUT/Image" | cut -f1))"

# ---- 6. 定制：fstab / 属性 / 清理 ----
log "写入 fstab.stararm（/data ← 覆盖盘 vda2，首启自动格式化）"
find "$STAGING" -maxdepth 4 -name 'fstab.*' -not -name 'fstab.stararm' -delete || true
for dest in "$STAGING/fstab.stararm" "$STAGING/system/etc/fstab.stararm"; do
  mkdir -p "$(dirname "$dest")"
  printf '%s\n' \
    '# <src>   <mnt_point> <type> <mount_flags> <fs_mgr_flags>' \
    '/dev/vda2  /data      ext4   defaults     wait,formattable,check,latemount' \
    > "$dest"
done

log "写入属性（adbd TCP 5555）"
BP="$STAGING/system/build.prop"
if [ -f "$BP" ]; then
  grep -q '^service.adb.tcp.port=' "$BP" 2>/dev/null \
    || printf 'service.adb.tcp.port=5555\npersist.service.adb.tcp.port=5555\n' >> "$BP"
else
  log "  警告: 未找到 system/build.prop"
fi

if [ -n "$PRUNE" ]; then
  log "裁剪: $PRUNE"
  for pat in $PRUNE; do
    # shellcheck disable=SC2086
    rm -rf "$STAGING/$pat" 2>/dev/null || true
  done
fi

mkdir -p "$STAGING/data"

# ---- 7. 打包为单 ext4（保留源 uid/gid/mode + SELinux 上下文）----
log "汇总 file_contexts"
FC="$WORK/combined_file_contexts"
: > "$FC"
while IFS= read -r f; do
  cat "$f" >> "$FC" || true
done < <(find "$STAGING" -path '*/selinux/*file_contexts*' -type f 2>/dev/null | sort)
[ -s "$FC" ] || log "  警告: 未找到 file_contexts（将以默认标签写入）"

BYTES=$(du -sb "$STAGING" | cut -f1)
SIZE=$((BYTES + BYTES / 5 + 536870912))
log "根文件系统: 内容 $(numfmt --to=iec "$BYTES") → 镜像 $(numfmt --to=iec "$SIZE")"
rm -f "$OUT/system.img"
mkuserimg_mke2fs "$STAGING" "$OUT/system.img" ext4 / "$SIZE" \
  -j 0 -T 0 -L stararm --inode_size 256 "$FC" \
  || die "mkuserimg_mke2fs 失败"
log "system.img: $(du -h "$OUT/system.img" | cut -f1)"

# sudo 重入时把产物交还给调用用户，便于后续步骤写入
if [ -n "${SUDO_USER:-}" ]; then
  chown -R "$SUDO_USER" "$OUT" || true
fi
log "完成: $OUT/{Image,system.img}"
