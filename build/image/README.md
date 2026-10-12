# StarARM 镜像组装流水线

不做完整 AOSP 编译，而是下载 ci.android.com 的现成构建产物，在 CI 里**组装**成 StarARM
约定的镜像（`image.json` + `Image` + 单根分区 `system.img`）。

```
fetch.py ──► assemble.sh ──► mkimage.py ──► boot_test.sh
(ci产物下载)  (super拆分+ramdisk合并)  (image.json+打包)   (TCG启动冒烟)
                 ▲
            build.sh（总编排，本地/CI 通用）
```

## 各脚本

| 文件 | 作用 |
| --- | --- |
| `fetch.py` | 解析分支最近成功构建（`status.json`），列产物（`BUILD_INFO`），断点续传下载（`Range`） |
| `assemble.sh` | `lpunpack` 拆 `super.img` → 挂载 system/vendor/product/… 合并为一棵根树 → 合入 `init_boot`/`vendor_boot` ramdisk（得 `/init`）→ 写 `fstab.stararm`/adbd 属性 → `mkuserimg_mke2fs` 打成单 ext4 |
| `mkimage.py` | 生成 `image.json`、打包 `<image_id>.zip`、`--max-gb` 发布门禁（默认 1.9GB，GitHub Release 上限 2GiB） |
| `boot_test.sh` | 按 `core/qemu_manager.py build_args` 契约用 TCG 启动，轮询 `adb shell getprop sys.boot_completed`；`serial.log`/`qemu.log` 留档 |
| `build.sh` | 串联以上步骤；环境变量见脚本头部（`BRANCH/TARGET/BUILD_ID/IMAGE_ID/PRUNE/BOOT_TEST/MAX_GB`…） |

## 本地用法（需 Linux + 免密 sudo + ≥20GB 空闲盘）

```bash
bash build/image/build.sh                 # 下载→组装→打包→启动冒烟
BOOT_TEST=0 bash build/image/build.sh     # 跳过冒烟
PRUNE="system/media system/framework/arm" bash build/image/build.sh   # 体积超限时裁剪
```

## CI 用法

Actions → **build-image** → `Run workflow`：

- `branch`/`target`/`build_id`：产物来源（默认 `aosp-android14-gsi` +
  `aosp_cf_arm64_phone-userdebug`，`build_id` 留空取分支最近成功构建）；
- `image_id`/`image_name`/`android_version`：写入 `image.json`；
- `boot_test`：TCG 启动冒烟（10–30 分钟，失败看 `image-logs-*` artifact 的 `serial.log`）；
- `publish_release`：上传到 GitHub Release（tag `images`，>2GiB 拒绝）；
- `publish_hf`：上传 HuggingFace 数据集（需仓库 secrets `HF_TOKEN`）。

## 镜像契约（务必保持）

- 内核 `Image` + `-M virt -cpu cortex-a76`，无 initrd（`/init` 在根分区）；
  内核为 CF 同款 GKI（ikconfig 实证：**无任何 virtio 驱动**，有 NVMe/xhci/ext4/erofs）；
- `cmdline`：`root=/dev/nvme0n1 rootwait`、`androidboot.hardware=stararm`、`androidboot.selinux=permissive`
  （组装镜像未重签 verity/AVB，必须 permissive + 解锁状态；`rootwait` 等 NVMe PCIe 异步探测）；
- **nvme0n1** = 只读根分区（`system.img`），**nvme1n1** = 实例 qcow2 覆盖层 → 由
  `fstab.stararm` 挂载为 `/data`，`formattable` 首启自动格式化；
- 网卡 = `qemu-xhci` + `usb-net`（CDC ECM/RNDIS，guest 端 `cdc_ether`/`usbnet` 模块在
  system_dlkm）；ADB 管理通道始终走用户网络 `hostfwd`；
- adbd 监听 TCP 5555（`service.adb.tcp.port` 已写入 `system/build.prop`）。

## 已知风险 / 失败排查

| 症状 | 方向 |
| --- | --- |
| 串口 `Kernel panic: VFS: Unable to mount root fs` 或 `error -6` | NVMe 枚举失败：查 serial 中 `nvme`/`pci` 行；确认 `cmdline` 含 `root=/dev/nvme0n1 rootwait`、盘序 hd0=root |
| 串口有 `nvme` 但无 adb（TCP 5555 不通） | usb-net 枚举失败 → 查 `xhci`/`cdc_ether` 行；或 `cdc_ether` 未在 `modules.load` 自动加载 → `adb shell lsmod`（需先串口诊断） |
| `init: ...` 反复重启 | 看 `serial.log` 中 fstab/`/data` 报错；确认 `fstab.stararm` 已覆盖厂商 fstab |
| 特权域被拒 | 保持 `androidboot.selinux=permissive`；后续可做 sepolicy 定制 |
| zip 超 1.9GB | 增大 `PRUNE`（如 `system/media`、32 位库、预置 APK）后重建 |
| 磁盘不足 | workflow 已在开头删除 Android SDK/dotnet 等（约 +15GB）；`assemble.sh` 会在解包后即时删除 `super`/`parts` |

产物与清单格式见 `mirror/images/README.md`；发布（GitHub + HuggingFace）见
`build/publish_images.ps1` 与 `build/upload_hf.py`。
