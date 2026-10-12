#!/usr/bin/env bash
# StarARM 镜像组装总编排：fetch → assemble → mkimage → (可选) boot_test
# 用法（本地/CI 一致）:
#   bash build/image/build.sh
# 可用环境变量见下方默认值。
set -euo pipefail
cd "$(dirname "$0")/../.."   # 仓库根目录

BRANCH="${BRANCH:-aosp-android14-gsi}"
TARGET="${TARGET:-aosp_cf_arm64_phone-userdebug}"
BUILD_ID="${BUILD_ID:-}"
IMAGE_ID="${IMAGE_ID:-aosp-14-arm64}"
IMAGE_NAME="${IMAGE_NAME:-AOSP 14 (ARM64)}"
ANDROID_VERSION="${ANDROID_VERSION:-14}"
PRUNE="${PRUNE:-}"
BOOT_TEST="${BOOT_TEST:-1}"
MAX_GB="${MAX_GB:-1.9}"
WORK="${WORK:-.work}"
OUT="${OUT:-dist}"
KEEP_INPUTS="${KEEP_INPUTS:-0}"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || PY=python

log() { echo "[build] $*"; }

# ---- 1. 解析 build id 并下载 ----
if [ -z "$BUILD_ID" ]; then
  log "解析 $BRANCH/$TARGET 最近成功构建"
  BUILD_ID=$("$PY" - "$BRANCH" "$TARGET" <<'EOF'
import os, sys
sys.path.insert(0, "build/image")
from fetch import resolve_build_id
print(resolve_build_id(sys.argv[1], sys.argv[2]))
EOF
)
fi
IMG_NAME=$($PY build/image/fetch.py --build-id "$BUILD_ID" --target "$TARGET" --list \
  | tr -d ' ' | grep -m1 -- "-img-${BUILD_ID}\.zip$" || true)
[ -n "$IMG_NAME" ] || { echo "[build] 未找到 $TARGET 的 img zip（build_id=$BUILD_ID）" >&2; exit 1; }
IMG_ZIP="$WORK/$IMG_NAME"
OTO_ZIP="$WORK/otatools.zip"
mkdir -p "$WORK" "$OUT"

log "下载产物 (build_id=$BUILD_ID, img=$IMG_NAME)"
$PY build/image/fetch.py --build-id "$BUILD_ID" --target "$TARGET" \
  --out "$WORK" --download "$IMG_NAME" "otatools.zip"

# ---- 2. 组装 ----
log "组装根分区镜像"
WORK="$WORK" OUT="$OUT" IMG_ZIP="$IMG_ZIP" OTATOOLS_ZIP="$OTO_ZIP" PRUNE="$PRUNE" \
  bash build/image/assemble.sh

if [ "$KEEP_INPUTS" != "1" ]; then
  rm -f "$IMG_ZIP" "$OTO_ZIP"
  rm -rf "$WORK/images" "$WORK/parts"
  log "已清理输入包（KEEP_INPUTS=1 可保留）"
fi

# ---- 3. 打包 ----
ZIP_OUT="$OUT/${IMAGE_ID}.zip"
log "打包 $ZIP_OUT"
$PY build/image/mkimage.py --dir "$OUT" --id "$IMAGE_ID" --name "$IMAGE_NAME" \
  --version "$ANDROID_VERSION" --out "$ZIP_OUT" --max-gb "$MAX_GB"

# ---- 4. 启动冒烟（可选）----
if [ "$BOOT_TEST" = "1" ]; then
  log "启动冒烟测试（TCG）"
  DIST="$OUT" WORK="$WORK" bash build/image/boot_test.sh
else
  log "跳过启动冒烟（BOOT_TEST=0）"
fi

log "完成: $ZIP_OUT"
ls -l "$OUT"
