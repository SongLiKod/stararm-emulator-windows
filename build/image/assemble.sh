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
log "lpunpack 输出:"
ls -la "$WORK/parts" | sed 's/^/    /' || true
[ -n "$(ls -A "$WORK/parts" 2>/dev/null)" ] || die "lpunpack 未产出任何分区文件"

# ---- 3. 各逻辑分区 → 合并根 ----
# 依据（本构建 build 16571446 实测）：
#   * super_empty.img LP 元数据：分区名为 system_a/vendor_a/...（ab_update=true，A/B 槽位）
#   * lpunpack.cc:259 输出 = output_dir/ + GetPartitionName() + ".img"
#   * super_misc_info.txt：*_fs_type=erofs、*_disable_sparse=true（super 内为裸 erofs）
#   * _b 槽位 0 extents → lpunpack 产出 0 字节文件，不得选用
find_part() { # part_name → 打印实际文件路径（无则失败）
  local n="$1" f
  for f in "${n}_a.img" "${n}.img" "${n}" "${n}_a"; do
    if [ -f "$WORK/parts/$f" ] && [ -s "$WORK/parts/$f" ]; then
      echo "$WORK/parts/$f"; return 0
    fi
  done
  return 1
}

mount_copy() { # part_name
  local name="$1" raw sparse="$WORK/parts/$1.simg" mnt="$WORK/mnt"
  raw=$(find_part "$name") || { log "  $name: 跳过（super 中无非空分区文件）"; return 0; }
  log "  $name ← $(basename "$raw") ($(du -h "$raw" | cut -f1))"
  rm -f "$sparse"
  simg2img "$raw" "$sparse" 2>/dev/null || cp "$raw" "$sparse"
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
  rm -f "$raw"   # 已并入 staging，释放空间
}

# 本构建分区为 erofs（super_misc_info.txt: *_fs_type=erofs），确保内核模块就绪
modprobe erofs 2>/dev/null || true
grep -qw erofs /proc/filesystems && log "内核支持 erofs" \
  || log "警告: 内核未见 erofs（挂载可能失败，关注下方 mount 报错）"

for part in system system_ext vendor product odm system_dlkm vendor_dlkm odm_dlkm; do
  mount_copy "$part"
done
[ -d "$STAGING/system" ] || die "合并根缺少 /system（检查上方 lpunpack 输出与挂载日志）"
log "staging 根目录: $(ls "$STAGING" | tr '\n' ' ')"

# ---- 4. ramdisk(init_boot 通用 + vendor_boot 厂商) 合入根 ----
extract_ramdisk() { # boot_img outdir → 打印解包目录
  local img="$1" out="$2"
  rm -rf "$out"; mkdir -p "$out"
  unpack_bootimg --boot_img "$img" --out "$out" >/dev/null
  local rd
  rd=$(find "$out" -maxdepth 2 -name '*ramdisk*' -type f | head -n1 || true)
  [ -n "$rd" ] || die "$img 未找到 ramdisk（输出: $(ls "$out" | tr '\n' ' ')）"
  local tmp="$out/rd"; rm -rf "$tmp"; mkdir -p "$tmp"
  # super_misc_info.txt: lz4_ramdisks=true → ramdisk 可能为 lz4；同时兜底 gzip/zstd/裸 cpio
  if gzip -t "$rd" 2>/dev/null; then
    (cd "$tmp" && gzip -dc "$rd" | cpio -idmu --quiet)
  elif zstd -t "$rd" 2>/dev/null; then
    (cd "$tmp" && zstd -dc "$rd" | cpio -idmu --quiet)
  elif command -v lz4 >/dev/null && lz4 -t "$rd" >/dev/null 2>&1; then
    (cd "$tmp" && lz4 -dc "$rd" | cpio -idmu --quiet)
  elif [ "$(head -c 5 "$rd")" = "07070" ]; then
    (cd "$tmp" && cpio -idmu --quiet < "$rd")
  else
    die "$img: ramdisk 压缩格式无法识别（前4字节: $(od -A n -t x1 -N 4 "$rd" | tr -d ' ')）"
  fi
  echo "$tmp"
}

log "合入 init_boot ramdisk"
RD_SYS=$(extract_ramdisk "$WORK/images/init_boot.img" "$WORK/rd_init")
rsync -a --ignore-existing "$RD_SYS/" "$STAGING/"

log "合入 vendor_boot ramdisk"
if [ -s "$WORK/images/vendor_boot.img" ]; then
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
[ -f "$BP" ] || BP="$STAGING/build.prop"
if [ -f "$BP" ]; then
  log "  $BP"
  grep -q '^service.adb.tcp.port=' "$BP" 2>/dev/null \
    || printf 'service.adb.tcp.port=5555\npersist.service.adb.tcp.port=5555\n' >> "$BP"
else
  log "  警告: 未找到 build.prop"
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
# 只汇总文本 file_contexts；本构建 *_selinux_fc 指向 file_contexts.bin（二进制，混入会损坏规则）
while IFS= read -r f; do
  cat "$f" >> "$FC" || true
done < <(find "$STAGING" -path '*/selinux/*file_contexts*' -type f ! -name '*.bin' 2>/dev/null | sort)
[ -s "$FC" ] || log "  警告: 未找到 file_contexts（将以默认标签写入）"

# 组装根新增/改名的路径可能不在原 file_contexts 中；e2fsdroid 查不到标签会直接失败，
# 按需补齐（同正则已存在则跳过，避免重复规则），最后加兜底规则。
add_fc() { # regex context —— 用 ENVIRON 传参避免 awk -v 处理反斜杠转义
  if ! FC_R="$1" awk 'BEGIN{r=ENVIRON["FC_R"]; f=1} $1==r{f=0} END{exit f}' "$FC"; then
    printf '%s %s\n' "$1" "$2" >> "$FC"
    echo "    + $1 $2"
  fi
}
add_fc '/'                      'u:object_r:rootfs:s0'
add_fc '/data'                  'u:object_r:system_data_file:s0'
add_fc '/fstab\\..*'            'u:object_r:rootfs:s0'
add_fc '/system/etc/fstab\\..*' 'u:object_r:system_file:s0'
add_fc '/init'                  'u:object_r:init_exec:s0'
add_fc '/init\\..*'             'u:object_r:init_exec:s0'
add_fc '.*'                     'u:object_r:system_file:s0'
echo "[assemble]   file_contexts 规则数: $(grep -c '' "$FC")"

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
