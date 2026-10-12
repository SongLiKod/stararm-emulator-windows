#!/usr/bin/env bash
# StarARM 镜像启动冒烟测试（CI 用 TCG，无需 KVM）：
#   按 core/qemu_manager.py build_args 契约启动 → 轮询 adb sys.boot_completed=1 → 判定成功
# 内核 ikconfig 实证无 virtio 驱动（# CONFIG_VIRTIO_BLK/_NET/_MMIO is not set）：
#   根盘/数据盘 = NVMe（CONFIG_BLK_DEV_NVME=y），根盘为只读基盘的 CoW qcow2
#   （ext4 挂载需写超级块，readonly 盘会被 QEMU 拒写 EPERM），
#   网卡 = qemu-xhci + usb-net（CDC ECM，guest 端 cdc_ether/usbnet 在 system_dlkm），
#   无 virtio-gpu/rng 设备（后端无驱动，忽略）。
# 产物: $WORK/serial.log（内核/init 日志）、$WORK/qemu.log、$WORK/boot-test-*.txt
set -euo pipefail

DIST="${DIST:-dist}"
WORK="${WORK:-.work}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-2400}"   # TCG 下 Android 启动可能超过 20 分钟
MEM_MB="${MEM_MB:-3072}"
SMP="${SMP:-4}"
ADB_PORT="${ADB_PORT:-5555}"
QEMU="${QEMU:-qemu-system-aarch64}"
ADB="${ADB:-adb}"

# qemu-img -b 的相对 backing 路径按新 qcow2 所在目录解析 → DIST 须为绝对路径
case "$DIST" in /*) : ;; *) DIST="$PWD/$DIST" ;; esac
case "$WORK" in /*) : ;; *) WORK="$PWD/$WORK" ;; esac

log() { echo "[boot-test] $*"; }
fail() {
  echo "[boot-test] FAIL: $*" >&2
  echo "--- serial.log 尾部 ---"
  tail -n 150 "$SERIAL" 2>/dev/null || true
  echo "--- panic/bug 扫描 ---"
  grep -E -m 20 'Kernel panic|BUG:|Unable to handle|init: |sys.boot_completed' "$SERIAL" 2>/dev/null | tail -n 40 || true
  echo "--- qemu.log 尾部 ---"
  tail -n 40 "$WORK/qemu.log" 2>/dev/null || true
  exit 1
}

[ -f "$DIST/Image" ] && [ -f "$DIST/system.img" ] && [ -f "$DIST/image.json" ] \
  || { echo "[boot-test] 缺少 $DIST/{Image,system.img,image.json}" >&2; exit 2; }
command -v "$QEMU" >/dev/null || { echo "[boot-test] 未安装 $QEMU" >&2; exit 2; }
command -v "$ADB" >/dev/null || { echo "[boot-test] 未安装 adb" >&2; exit 2; }

CMDLINE=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['cmdline'])" "$DIST/image.json")
log "cmdline: $CMDLINE"

mkdir -p "$WORK"
# root：只读基盘 + 实例 CoW qcow2（ext4 挂载需写超级块；实证 readonly 盘会被
# QEMU 拒写 EPERM → 挂根失败）。data：独立 qcow2 → fstab /dev/nvme1n1 formattable
qemu-img create -f qcow2 -b "$DIST/system.img" -F raw "$WORK/root.qcow2" >/dev/null
qemu-img create -f qcow2 "$WORK/data.qcow2" 8G >/dev/null
SERIAL="$WORK/serial.log"
: > "$SERIAL"

"$QEMU" \
  -M virt -cpu cortex-a76 -smp "$SMP" -m "${MEM_MB}M" \
  -accel tcg,thread=multi -name stararm-ci \
  -kernel "$DIST/Image" \
  -append "$CMDLINE androidboot.serialno=stararmci01" \
  -drive "if=none,file=$WORK/root.qcow2,format=qcow2,id=hd0" \
  -device nvme,drive=hd0,serial=stararm0 \
  -drive "if=none,file=$WORK/data.qcow2,format=qcow2,id=hd1" \
  -device nvme,drive=hd1,serial=stararm1 \
  -display none \
  -device qemu-xhci,id=xhci \
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:${ADB_PORT}-:5555" \
  -device usb-net,netdev=net0 \
  -serial "file:$SERIAL" -monitor none \
  > "$WORK/qemu.log" 2>&1 &
QPID=$!
trap 'kill $QPID 2>/dev/null || true; wait $QPID 2>/dev/null || true' EXIT
log "qemu pid=$QPID，超时 ${BOOT_TIMEOUT}s"

"$ADB" start-server >/dev/null 2>&1 || true
deadline=$(( $(date +%s) + BOOT_TIMEOUT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  kill -0 "$QPID" 2>/dev/null || fail "qemu 提前退出（检查 kernel/驱动/启动参数）"
  "$ADB" connect "127.0.0.1:${ADB_PORT}" >/dev/null 2>&1 || true
  state=$("$ADB" -s "127.0.0.1:${ADB_PORT}" shell getprop sys.boot_completed 2>/dev/null \
    | tr -d '\r' || true)
  if [ "$state" = "1" ]; then
    log "启动成功: sys.boot_completed=1"
    "$ADB" -s "127.0.0.1:${ADB_PORT}" shell getprop ro.build.fingerprint 2>/dev/null \
      | tr -d '\r' | tee "$WORK/boot-fingerprint.txt" || true
    "$ADB" disconnect "127.0.0.1:${ADB_PORT}" >/dev/null 2>&1 || true
    kill "$QPID" 2>/dev/null || true
    wait "$QPID" 2>/dev/null || true
    trap - EXIT
    log "serial 日志: $SERIAL"
    exit 0
  fi
  if grep -q -E 'Kernel panic|VFS: Unable to mount root' "$SERIAL" 2>/dev/null; then
    fail "串口日志出现 panic/mount 失败"
  fi
  sleep 15
done
fail "等待启动超时（${BOOT_TIMEOUT}s），adb state='$state'"
