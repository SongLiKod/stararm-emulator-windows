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
- **nvme0n1** = 根分区（**只读基盘 `system.img` 的实例 CoW qcow2**，可写；CI 实证
  只读盘挂载时 ext4 写超级块会被 QEMU 拒写 EPERM，基盘本身永不挂载→跨实例隔离），
  **nvme1n1** = 实例 qcow2 数据盘（`fstab.stararm` 挂载为 `/data`，`formattable`
  首启自动格式化）；
- 网卡 = `qemu-xhci` + `usb-net`（CDC ECM/RNDIS，guest 端 `cdc_ether`/`usbnet` 模块在
  system_dlkm）；ADB 管理通道始终走用户网络 `hostfwd`；
- adbd 监听 TCP 5555（`service.adb.tcp.port` 已写入 `system/build.prop`）。

## 已知风险 / 失败排查

| 症状 | 方向 |
| --- | --- |
| 串口 `Kernel panic: VFS: Unable to mount root fs` 或 `error -6` | NVMe 枚举失败：查 serial 中 `nvme`/`pci` 行；确认 `cmdline` 含 `root=/dev/nvme0n1 rootwait`、盘序 hd0=root |
| 串口有 `nvme` 但无 adb（TCP 5555 不通） | QEMU usb-net 只讲 RNDIS、guest 无 `rndis_host`（`cdc_ether` 绑不上）→ 无 IP；`boot_test` 完成判定已改扫串口 `STARARM_BOOT_COMPLETED=1`，adb 仅作可选加速 |
| `init: ...` 反复重启 | 看 `serial.log` 中 fstab/`/data` 报错；确认 `fstab.stararm` 已覆盖厂商 fstab |
| 串口 `bootstrap-apexd-failed` 反复重启 | 同模块名重复 apex（camera HAL `fastscenecycle` 变体）→ `assemble.sh` 启动时去重 |
| 串口 `reboot,boringssl-self-check-failed` | 两种成因均已修：① FC 汇总顺序（libselinux 反向扫描「最后一条匹配的 meta 规则获胜」，兜底 `.*` 必须置顶，vendor boringssl 用静态精确规则）；② `apexd.status=ready` 后 apex 变体自检找 `/apex/com.android.conscrypt/bin/boringssl_self_test32` 不存在 → `init.boringssl*.rc` 已删 |
| 串口 `reboot,apexd-failed`（apexd SIGABRT 于 `GetSessionsDir`，post-fs-data mkdir 报 EROFS） | /data 未挂载 → `mount_all` 必须写在 `init.${ro.hardware}.rc`（`assemble.sh` 已内置 `init.stararm.rc`）；另需删 `/system/bin/recovery` 防 `InRecovery()` 使默认 fstab 搜索失效 |
| 串口 `Cannot add a device manifest to a framework manifest` / `Cannot add a framework manifest to a device manifest` + zygote 秒退 exit1 | VINTF 片段分两类：`android.hardware.*` 是设备侧（须在 vendor），其余（如 `android.system.suspend-service.xml`）是框架侧（须留在 system）；混放会导致一侧 manifest 解析整体失败（NULL VINTF）→ servicemanager 查不到 HAL → zygote crash-loop |
| zygote 反复重启、SF SIGABRT `couldn't find an OpenGL ES implementation` | 712eb10 实证：`ro.boot.*` 图形属性缺失 + 无硬件渲染路径 → SF RenderEngine `eglGetDisplay` 失败 → onrestart 级联杀 zygote（永不 fork system_server）。修法：cmdline 注入 `androidboot.hardware.egl=mesa` 等软渲染属性（见 `mkimage.py` DEFAULT_CMDLINE，取值对齐 CF `qemu_manager.cpp`）+ 剥离 minigbm mapper 回退软件 gralloc0 + 恢复 hwc3（ranchu）验证注册；**硬约束**：内核无 `VIRTIO_PCI`/`DRM_VIRTIO_GPU`/`VGEM`/`VKMS`/`PL111`、上游 QEMU 无 goldfish → minigbm/DRM/`/dev/fb` 永不可用，仅剩 mesa(llvmpipe) 软渲染一条路 |
| boot_service/gatekeeper/oemlock/keymint 反复 SIGABRT/连接失败 | 全为宿主依赖（无宿主 socket/`/dev/hvc11`，内核无 `VIRTIO_CONSOLE`）→ `assemble.sh` `disable_rc` 已停 `*boot-service*`/`*gatekeeper-service.remote*`/`*oemlock-service.remote*`/`*keymint-service.rust*`（712eb10 serial 计数 ×495/×411/×454/×1） |
| 特权域被拒 | 保持 `androidboot.selinux=permissive`；后续可做 sepolicy 定制 |
| zip 超 1.9GB | 增大 `PRUNE`（如 `system/media`、32 位库、预置 APK）后重建 |
| 磁盘不足 | workflow 已在开头删除 Android SDK/dotnet 等（约 +15GB）；`assemble.sh` 会在解包后即时删除 `super`/`parts` |

产物与清单格式见 `mirror/images/README.md`；发布（GitHub + HuggingFace）见
`build/publish_images.ps1` 与 `build/upload_hf.py`。
