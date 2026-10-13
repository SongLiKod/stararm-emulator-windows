#!/usr/bin/env bash
# 把 Cuttlefish/AOSP 的 super.img + boot/init_boot/vendor_boot 组装成 StarARM 约定的单分区镜像：
#   staging 根分区 = init_boot 通用 ramdisk(/init 等) + vendor ramdisk + system/system_ext/vendor/product/odm 合并树
#   /data 由实例覆盖盘（qcow2 → /dev/nvme1n1，第二块 NVMe）提供，fstab.stararm 负责首启格式化挂载
# 依赖: otatools(lpunpack/simg2img/mkuserimg_mke2fs/unpack_bootimg), e2fsprogs, cpio, unzip, sudo(loop mount)
set -euo pipefail

WORK="${WORK:-.work}"
OUT="${OUT:-dist}"
IMG_ZIP="${IMG_ZIP:-}"
OTATOOLS_ZIP="${OTATOOLS_ZIP:-}"
PRUNE="${PRUNE:-}"
# 相对路径必须转绝对：PATH 中的相对项（.work/otatools/bin）在子 shell 的 cd 之后会失效。
# 实测（run 38279546089）：lz4 -t 在仓库根执行成功，(cd ... && lz4 -dc) 报 No such file or directory。
case "$WORK" in /*) : ;; *) WORK="$PWD/$WORK" ;; esac
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

# 以 root 产生的文件在退出时（成功或失败）交还调用用户，
# 否则 build.sh 后续 rm/打包/产物收集会报 Permission denied（run 38279546089 实测）。
if [ -n "${SUDO_USER:-}" ]; then
  handback() { chown -R "$SUDO_USER" "$WORK" "$OUT" 2>/dev/null || true; }
  trap handback EXIT
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
  # 注意：本函数在 $( ) 中调用，set -e 在命令替换里不生效（实测），
  # 解压分支必须显式 `|| die`，并校验结果非空，否则失败会被静默吞掉。
  if gzip -t "$rd" 2>/dev/null; then
    (cd "$tmp" && gzip -dc "$rd" | cpio -idmu --quiet) || die "$img: gzip ramdisk 解压失败"
  elif zstd -t "$rd" 2>/dev/null; then
    (cd "$tmp" && zstd -dc "$rd" | cpio -idmu --quiet) || die "$img: zstd ramdisk 解压失败"
  elif command -v lz4 >/dev/null && lz4 -t "$rd" >/dev/null 2>&1; then
    (cd "$tmp" && lz4 -dc "$rd" | cpio -idmu --quiet) || die "$img: lz4 ramdisk 解压失败"
  elif [ "$(head -c 5 "$rd")" = "07070" ]; then
    (cd "$tmp" && cpio -idmu --quiet < "$rd") || die "$img: 裸 cpio ramdisk 解压失败"
  else
    die "$img: ramdisk 压缩格式无法识别（前4字节: $(od -A n -t x1 -N 4 "$rd" | tr -d ' ')）"
  fi
  [ -n "$(ls -A "$tmp" 2>/dev/null)" ] || die "$img: ramdisk 解压结果为空"
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
log "写入 fstab.stararm（/data ← 覆盖盘 nvme1n1，首启自动格式化）"
find "$STAGING" -maxdepth 4 -name 'fstab.*' -not -name 'fstab.stararm' -delete || true
for dest in "$STAGING/fstab.stararm" "$STAGING/system/etc/fstab.stararm"; do
  mkdir -p "$(dirname "$dest")"
  printf '%s\n' \
    '# <src>   <mnt_point> <type> <mount_flags> <fs_mgr_flags>' \
    '/dev/nvme1n1 /data      ext4   defaults     wait,formattable,check,latemount' \
    > "$dest"
done
# AOSP system/core/rootdir/init.rc 只有 import /init.${ro.hardware}.rc，mount_all 必须由
# 设备专属 rc 执行（init.rc 注释原话："Mount fstab in init.{$device}.rc by mount_all command"）。
# 实证（run 38325957483）：缺 init.stararm.rc → mount_all 从未执行 → /data 从未挂载 →
# post-fs-data mkdir 全部 EROFS → apexd GetSessionsDir() CHECK 失败 SIGABRT → reboot,apexd-failed。
cat > "$STAGING/init.stararm.rc" <<'EOF'
on post-fs
    # run fd3746a 实证：mesa EGL 已能 eglGetDisplay/Initialize，但 chooseConfig 0 configs
    # （无 /dev/dri → android 平台 EGL 不提供 RECORDABLE/FRAMEBUFFER_TARGET 配置）。
    # vendor_dlkm 自带 vkms.ko（纯软 DRM，虚拟 connector + dumb buffer，无硬件依赖）。
    # run 7e16fa6 实证 vkms 加载成功（[drm] Initialized vkms）+ minigbm allocator 正常，
    # 但 mesa(android) 需 virgl/venus Gallium 驱动 → 纯软 vkms 无 3D → mesa 0 configs 死路。
    # run fb6e4c8 实证 egl=angle 同样 0 configs（ANGLE eglInitialize 已过，疑无可用
    # Vulkan ICD 或 vendor goldfish ANGLE 缺 android RECORDABLE/FRAMEBUFFER_TARGET 属性）。
    exec -- /system/bin/modprobe -d /vendor_dlkm/lib/modules vkms

# 串口探针（fb6e4c8 实证：init exec sh 因 shell_exec 无 init 域转移而失败；
# 改 service console + toybox（toolbox 域，与 modprobe 同域已验证可跑）→ 输出进 /dev/console）。
# 目的：EGL/Vulkan ICD 文件真实清单（find 诊断曾截断）+ 未挂载 apex 文件排查。
service stararm.probe /system/bin/toybox ls -la /dev/dri /system/lib64/egl /vendor/lib64/egl /system_ext/lib64/egl /product/lib64/egl /system/etc/vulkan/icd.d /vendor/etc/vulkan/icd.d /vendor/lib64/hw /system/apex /system_ext/apex /vendor/apex /product/apex
    class core
    user root
    group root
    oneshot
    console

on post-fs-data
    start stararm.probe

on late-fs
    mount_all /fstab.stararm --late

on property:sys.boot_completed=1
    write /dev/console STARARM_BOOT_COMPLETED=1
EOF
log "已写入 /init.stararm.rc（post-fs 加载 vkms 软 DRM + late-fs 挂载 /data + boot_completed 串口标记）"
# libfstab InRecovery() 只探测 /system/bin/recovery 或 /sbin/recovery 是否存在；存在则所有
# ReadDefaultFstab 走 /etc/recovery.fstab 并落空（实证 run 38325957483 19.09s 日志：
# "failed to load fstab from : '/etc/recovery.fstab'" + "failed to find device default fstab"）。
# 本镜像不做 recovery 模式，删除该二进制恢复默认 fstab 搜索（/system/etc/fstab.stararm 可被找到）。
if [ -e "$STAGING/system/bin/recovery" ] || [ -e "$STAGING/sbin/recovery" ]; then
  log "删除 recovery 二进制（避免 InRecovery() 误判导致默认 fstab 搜索失效）"
fi
rm -f "$STAGING/system/bin/recovery" "$STAGING/sbin/recovery"

# 实证（run 38405769614 serial 801–823s）：apexd.status=ready 后 exec_start boringssl_self_test_apex32
# 找不到 /apex/com.android.conscrypt/bin/boringssl_self_test32（conscrypt apex 未含该二进制）→
# reboot_on_failure 触发 reboot,boringssl-self-check-failed → 整机重启循环。
# vendor 侧 early-init 自检与 /system/bin 自检均通过（serial 6–10s status 0），
# 删除系统侧 rc（含必然失败的 apex 变体动作）；vendor rc（/vendor/etc/boringssl_self_test.*.rc）保留。
if ls "$STAGING/system/etc/init/hw/init.boringssl"*.rc >/dev/null 2>&1; then
  log "删除 init.boringssl*.rc（apex 内 boringssl_self_test32 不存在，apexd.status=ready 必触发重启）"
fi
rm -f "$STAGING/system/etc/init/hw/init.boringssl"*.rc

# ---- Vulkan ICD 注入（run 8fa65e9 探针实证后的定案）----
# 8fa65e9 串口探针完整清单实证：
#   /system/lib64/egl、/system_ext|product/lib64/egl 均不存在（system 分区无 EGL 库）
#   /system|/vendor/etc/vulkan/icd.d 均不存在（无任何 ICD json）
#   /vendor/lib64/egl 仅 angle/emulation/mesa 壳（libGLESv2_angle 8.6MB，无 mesa 驱动后端）
#   /vendor/lib64/hw 有 vulkan.pastel.so（28.9MB，CF GuestSwiftshader 同款纯软 ICD）
#     与 vulkan.ranchu.so（135KB，需宿主 virgl）—— 但无 icd.d json → ANGLE 自带 loader
#     扫不到任何 ICD → eglInitialize 过但 0 configs（fb6e4c8/8fa65e9 实证）。
# 解法：① 把镜像自带 vulkan.pastel.so 用 icd.d json 暴露给 ANGLE loader；
#       ② 注入本仓库预编译 libvk_swiftshader.so（NDK r26 + SwiftShader master 自建，
#          纯 CPU JIT，无宿主依赖）作第二 ICD 兜底 —— loader 按文件名顺序尝试，
#          pastel 失败则落 swiftshader。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREBUILT="$SCRIPT_DIR/prebuilt"
if [ -f "$PREBUILT/libvk_swiftshader.so" ]; then
  mkdir -p "$STAGING/system/etc/vulkan/icd.d"
  install -m 0644 "$PREBUILT/vulkan.pastel.icd.json" "$STAGING/system/etc/vulkan/icd.d/0000_pastel.json"
  install -m 0644 "$PREBUILT/vulkan.swiftshader.icd.json" "$STAGING/system/etc/vulkan/icd.d/1000_swiftshader.json"
  install -m 0644 "$PREBUILT/libvk_swiftshader.so" "$STAGING/system/lib64/libvk_swiftshader.so"
  # libvulkan(hw 扫描) 与 ANGLE loader 双通道：hw 侧也放一份自建 ICD
  mkdir -p "$STAGING/vendor/lib64/hw"
  install -m 0644 "$PREBUILT/libvk_swiftshader.so" "$STAGING/vendor/lib64/hw/vulkan.swiftshader.so"
  log "已注入 Vulkan ICD（pastel json + 自建 swiftshader 34.7MB → system/lib64 + vendor/hw）"
else
  die "缺少 prebuilt/libvk_swiftshader.so（SwiftShader arm64 自建产物）"
fi

# CF 把设备侧 VINTF HAL 片段放进了 /system/etc/vintf/manifest（recovery-as-boot 布局）。
# run 38392785443 实证：framework manifest 报 "Cannot add a device manifest to a framework manifest"
# （health-service.cuttlefish.xml 是设备侧声明）→ 只移动 android.hardware.* 片段到 vendor。
# run 38405769614 实证（反例）：全量移动把框架侧片段（android.system.suspend-service.xml 等）
# 也挪进 vendor → device manifest 报 "Cannot add a framework manifest to a device manifest"
# → NULL VINTF MANIFEST: device → servicemanager 查不到任何设备 HAL →
# zygote 每次启动 exit1 crash-loop（system_server 从未 fork）。
SYS_MANIFEST="$STAGING/system/etc/vintf/manifest"
if ls "$SYS_MANIFEST"/android.hardware.*.xml >/dev/null 2>&1; then
  mkdir -p "$STAGING/vendor/etc/vintf/manifest"
  log "VINTF: system 侧 android.hardware.* 片段移至 vendor（框架侧片段留在 system）"
  mv "$SYS_MANIFEST"/android.hardware.*.xml "$STAGING/vendor/etc/vintf/manifest/"
fi

# 无 CF 宿主设备时必然失败、且会拖垮整机启动的 HAL 服务 rc（serial 实证）。
# 背景更正（run fd3746a 后）：内核内置配置无 DRM 后端，但 vendor_dlkm **自带模块**
# vkms.ko/pl111_drm.ko/goldfish_pipe.ko（CF 设备内核模块随镜像发布）——
# vkms 纯软 DRM 已由 init.stararm.rc post-fs 加载 → minigbm/allocator 恢复启用。
#   *boot-service*：SIGABRT(impl_.Init) ×495（run 712eb10，无 boot 分区设备）
#   *gatekeeper-service.remote* / *oemlock-service.remote*：连接失败 ×411/×454（宿主侧依赖）
#   *keymint-service.rust*：SIGABRT 打开 /dev/hvc11 失败（CF 宿主 virtio-console 通道，
#     内核无 VIRTIO_CONSOLE 且 vendor_dlkm 无 virtio_console.ko → 永不可用）
# hwc3.rc（ranchu composer）保持启用：run 712eb10 实证 device VINTF 修复后 ranchu 已能
# 注册（fd3746a serial "Found ... composer3.IComposer/default in device VINTF"）。
# system-suspend 的 register -3 属框架 manifest 解析失败的下游（VINTF 修复后预期消失），其 rc
# 在 APEX 内无法按文件停用，故不再 glob。
# 仅删 rc 停用服务，二进制保留便于后续诊断。
disable_rc() {
  find "$STAGING" -path '*/etc/init/*.rc' -name "$1" 2>/dev/null | while read -r rc; do
    log "停用 ($2): $rc"
    rm -f "$rc"
  done
}
# allocator.rc（minigbm）本轮恢复启用：vendor_dlkm 的 vkms.ko 提供 /dev/dri 软 DRM
# （init.stararm.rc post-fs modprobe），minigbm generic GBM 路径可用（CF DrmVirgl 同款配方）。
# minigbm mapper 不再剥离（gralloc4 栈恢复完整）。
disable_rc '*boot-service*'          'boot HAL impl_.Init SIGABRT ×495（无 boot 分区设备）'
disable_rc '*gatekeeper-service.remote*' '宿主侧 gatekeeper 连接失败 ×411'
disable_rc '*oemlock-service.remote*'    '宿主侧 oemlock 连接失败 ×454'
disable_rc '*keymint-service.rust*'  '需 /dev/hvc11 宿主通道（内核无 VIRTIO_CONSOLE 亦无对应模块）'

# 诊断：EGL/Vulkan/gralloc/mapper/allocator 文件全分区清单（run fd3746a head-60 截断于
# system/lib —— 本轮扩到 300 并补 vulkan ICD json/libvk*；运行时真相以 init.stararm.rc
# 串口探针为准）
log "诊断: EGL/Vulkan/gralloc/mapper/allocator 文件"
find "$STAGING" \( -path '*/egl/libEGL*' -o -path '*/egl/libGLES*' -o -name 'libvulkan*.so' \
  -o -name 'vulkan.*.so' -o -name 'libvk*' -o -path '*/vulkan/*' -o -name '*swiftshader*' \
  -o -name '*lavapipe*' -o -name '*lvp*' -o -name '*mesa*' \
  -o -name 'gralloc*' -o -name 'mapper*' -o -name 'android.hardware.graphics.mapper*' \
  -o -name 'android.hardware.graphics.allocator*' \) 2>/dev/null | head -300

log "诊断: 全部 apex 文件（排查 angle/swiftshader apex 是否存在但未挂载）"
find "$STAGING" -name '*.apex' 2>/dev/null | sed "s|$STAGING||" | head -80

# 诊断：图形栈 rc/二进制与 VINTF 现状（下轮若仍卡 SF 可据此定位）
log "诊断: 图形/合成器相关 rc"
find "$STAGING" -path '*/etc/init/*.rc' 2>/dev/null | xargs grep -lEi 'graphics|composer|surfaceflinger' 2>/dev/null | while read -r rc; do
  echo "=== RC $rc ==="; cat "$rc"
done || true
log "诊断: hw 二进制"
ls "$STAGING/system/bin/hw" "$STAGING/vendor/bin/hw" 2>/dev/null | grep -iE 'graphics|composer|allocator|health|boot-service|suspend' || true
log "诊断: VINTF manifest 目录"
ls "$STAGING/system/etc/vintf/manifest" "$STAGING/vendor/etc/vintf/manifest" 2>/dev/null || true

# apexd-bootstrap 同模块名去重（CI serial 实证：/vendor/apex 下 camera HAL 两个变体
# 同模块名 com.google.emulated.camera.provider.hal → apexd SIGABRT → bootstrap-apexd-failed）
# 扫描顺序 system→system_ext→product→vendor，仅此一对重复（前三段均通过）
DUP_APEX="$STAGING/vendor/apex/com.google.emulated.camera.provider.hal.fastscenecycle.apex"
if [ -f "$DUP_APEX" ]; then
  log "去除重复模块名 apex（保留默认 camera HAL 变体）: $(basename "$DUP_APEX")"
  rm -f "$DUP_APEX"
fi

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
# 兜底 .* 必须在文件最前：libselinux lookup_all 反向扫描（"最后一条匹配的 meta 规则获胜"），
# sort_specs 只把静态规则移到末尾（最先检查）。实证（run 38301659078）：.* 追加在末尾时成为
# 最后一条匹配规则 → 所有非静态命中的文件全被打成 system_file（boringssl 门禁因此 reboot）。
printf '%s %s\n' '.*' 'u:object_r:system_file:s0' > "$FC"
# 只汇总文本 file_contexts；本构建 *_selinux_fc 指向 file_contexts.bin（二进制，混入会损坏规则）
# 每文件后强制补一个换行（AOSP 构建同样强制插入），防止源文件缺尾换行时两文件首行粘连损坏规则
while IFS= read -r f; do
  cat "$f" >> "$FC" || true
  printf '\n' >> "$FC"
  echo "    FC<= $f ($(grep -c '' "$f") 行)"
done < <(find "$STAGING" -path '*/selinux/*file_contexts*' -type f ! -name '*.bin' 2>/dev/null | sort)
[ -s "$FC" ] || log "  警告: 未找到 file_contexts（将以默认标签写入）"
echo "    FC 内 boringssl 规则 $(grep -c 'bin/boringssl_self_test' "$FC") 条:"
grep 'bin/boringssl_self_test' "$FC" | sed 's/^/    FC: /' || true

# 组装根新增/改名的路径可能不在原 file_contexts 中；e2fsdroid 查不到标签会直接失败，
# 按需补齐（同正则已存在则跳过）。兜底 .* 已置顶，这里只补静态规则与缺失正则。
add_fc() { # regex context —— 用 ENVIRON 传参避免 awk -v 处理反斜杠转义
  if ! FC_R="$1" awk 'BEGIN{r=ENVIRON["FC_R"]; f=1} $1==r{f=0} END{exit f}' "$FC"; then
    printf '%s %s\n' "$1" "$2" >> "$FC"
    echo "    + $1 $2"
  fi
}
add_fc '/'                      'u:object_r:rootfs:s0'
add_fc '/data'                  'u:object_r:system_data_file:s0'
add_fc '/fstab\..*'             'u:object_r:rootfs:s0'
add_fc '/system/etc/fstab\..*'  'u:object_r:system_file:s0'
add_fc '/init'                  'u:object_r:init_exec:s0'
add_fc '/init\..*'              'u:object_r:rootfs:s0'
# 静态规则（无元字符）在反向扫描中最先检查、优先级最高。init exec_start 门禁硬性要求
# vendor 侧 boringssl 自检二进制标签为 vendor_boringssl_self_test_exec（AOSP
# system/sepolicy private/file_contexts 实证），否则 reboot,boringssl-self-check-failed。
add_fc '/vendor/bin/boringssl_self_test32' 'u:object_r:vendor_boringssl_self_test_exec:s0'
add_fc '/vendor/bin/boringssl_self_test64' 'u:object_r:vendor_boringssl_self_test_exec:s0'
echo "[assemble]   file_contexts 规则数: $(grep -c '' "$FC")"

BYTES=$(du -sb "$STAGING" | cut -f1)
SIZE=$((BYTES + BYTES / 5 + 536870912))
log "根文件系统: 内容 $(numfmt --to=iec "$BYTES") → 镜像 $(numfmt --to=iec "$SIZE")"
rm -f "$OUT/system.img"
mkuserimg_mke2fs "$STAGING" "$OUT/system.img" ext4 / "$SIZE" \
  -j 0 -T 0 -L stararm --inode_size 256 "$FC" \
  || die "mkuserimg_mke2fs 失败"
log "system.img: $(du -h "$OUT/system.img" | cut -f1)"

log "完成: $OUT/{Image,system.img}"
