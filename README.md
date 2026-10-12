# 星模ARM原生安卓模拟器（StarARM Emulator）

Windows 平台轻量化、可多开的**纯 ARM64 原生架构**安卓模拟器。基于 QEMU-aarch64 硬件整机仿真，在 X86 电脑上虚拟完整 ARM64 手机硬件，APK 原生执行 ARM 指令——无 X86 镜像、无二进制转译，从根源解决 ARM-only APK、加固应用、金融/小众 APP 的兼容、闪退与被检测问题。

## 功能特性（对应需求文档）

- **纯 ARM64 仿真**：QEMU `virt` + `cortex-a76` 整机仿真，仅支持 ARM64（aarch64）镜像，拒绝导入 X86 镜像；内置 Android 11-15 标准 AOSP ARM64 镜像定义，支持自定义镜像导入/导出/下载。
- **多实例多开**：新建 / 克隆（含磁盘）/ 复制（仅配置）/ 删除、批量启停删除配置、实例数据目录隔离、独立 qcow2 覆盖层、导出/导入/备份/还原。
- **资源超限保护**：全局最大实例数、总 CPU 核数、总内存阈值（0 = 按主机自动），创建与启动前校验。
- **图形渲染**：VirGL + Vulkan(Venus) / VirGL(OpenGL ES) / 软件渲染三级降级链；自定义分辨率（240P-4K）与 DPI；VNC 显示窗口支持缩放、全屏、截图、录屏。
- **虚拟化自适应**：多源检测 VT-x/AMD-V 固件开关、虚拟机监控程序（HypervisorPresent）与 Windows「虚拟机监控程序平台」（WHPX），区分「BIOS 未开启」/「仅 WHPX 功能未启用」/「已就绪」三种结论（修复 Hyper-V 运行时固件误报 False 导致的"已开启却提示未开启"）；未就绪时自动降级软件仿真并给出对应中文教程，WHPX 缺失时提供一键启用（UAC 提权）；启动失败按类别输出中文提示（虚拟化/图形/端口/桥接/磁盘/镜像）。
- **上手引导**：无实例时展示欢迎页（创建实例 → 启动 → 安装 APK 三步卡片 + 快捷入口），帮助菜单常驻「使用教程」图文说明。
- **外设与交互**：键鼠触摸映射、自定义宏脚本（循环/取消）、XInput 手柄映射、宿主-虚拟机剪贴板双向同步；APK 安装三入口：拖拽到窗口、工具栏「安装 APK」、实例行「更多 -> 安装 APK」（支持多选、批量安装到多个运行中实例）。
- **全维度硬件模拟**：品牌/型号/序列号/IMEI（Luhn 校验位）/Android ID/设备指纹随机生成与自定义、GPS 经纬度、电池电量与充电状态、弱化 QEMU 模拟器特征、NAT/桥接双网络模式。
- **自动化与 ADB**：每个实例独立 ADB 端口（5555-6000），完全兼容原生 ADB 协议与第三方工具；CLI 支持无 GUI 后台运维与批量自动化。
- **文件交互**：双向文件推送/拉取、共享文件夹增量双向同步、模拟器文件导出。
- **主题与多语言**：跟随系统 / 浅色 / 深色三套主题（配色严格按产品视觉规范，实时轮询系统主题）；简体中文/英文双语，默认跟随系统，切换实时生效。
- **无广告、无捆绑、无后台静默上传**（代码中仅有的外网访问为用户主动触发的镜像下载）。

## 目录结构

```
stararm-emulator-windows/
├── gui/        # Qt 6.5 UI、主题、VNC 显示、对话框、控件
├── core/       # QEMU 调度、实例管理、资源守卫、虚拟化检测、客户代理
├── adb/        # ADB 适配、端口分配、自动化、CLI
├── mirror/     # ARM64 镜像模型与镜像管理
├── config/     # 全局配置、路径、常量、主题、i18n（纯数据层）
├── tools/      # 截图录屏、文件同步、宏、键位、手柄、伪装、剪贴板
├── log/        # 系统/运行/错误三类日志（轮转、双语落盘）
├── resource/   # 语言包、主题配色、图标（纯数据，非 Python 包）
├── build/      # PyInstaller spec、打包/镜像/组件获取脚本、Qt IFW 安装器
├── tests/      # pytest 单元测试（不依赖 GUI，可无界面运行）
├── docs/       # 产品需求 + 技术落地文档
├── main.py     # GUI 入口
└── .github/workflows/build.yml  # CI：测试 + 打包 + Release
```

分层约束：`core/adb/mirror/config/tools/log` 均不依赖 PySide6，CLI 与单元测试可在无 GUI 环境运行。

## 开发与运行

```powershell
# 依赖：Python 3.10（Windows 10/11 64 位）
pip install -r requirements.txt          # PySide6==6.5.3（Qt 6.5 LTS）
pip install -r requirements-dev.txt      # pyinstaller==6.6.0, pytest==8.2.2

# 运行 GUI
python main.py

# 单元测试（无 GUI，STARARM_HOME 自动指向临时目录）
python -m pytest tests -q
```

`STARARM_HOME` 环境变量可覆盖用户数据目录（实例、镜像、日志、配置）。

## QEMU / ADB 组件

运行时按顺序查找 `qemu-system-aarch64`：全局设置指定路径 → 程序目录 `qemu/` 子目录 → `PATH`。ADB 同理（设置路径 / `adb-runtime/` / `PATH`）。

```powershell
./build/fetch_qemu.ps1 -Destination ./qemu         # 获取 QEMU 8.2 aarch64
./build/fetch_adb.ps1 -Destination ./adb-runtime   # 获取 platform-tools
./build/fetch_images.ps1                           # 从镜像源获取内置镜像
```

## 系统镜像来源

内置项只随包附带**镜像定义**（Android 11-15，`aosp-11-arm64` … `aosp-15-arm64`），镜像文件本体不随 git/安装包分发。程序内置 4 条镜像源（`resource/image_sources.json`，国内 2 + 海外 2），全局设置「镜像源」可选：

| 区域 | 源 | 地址 |
| --- | --- | --- |
| 国内 | ghfast.top（GitHub 加速） | `https://ghfast.top/https://github.com/SongLiKod/stararm-emulator-windows/releases/download/images` |
| 国内 | hf-mirror.com（HuggingFace 镜像） | `https://hf-mirror.com/datasets/SongLiKod/stararm-images/resolve/main` |
| 海外 | GitHub Releases（官方） | `https://github.com/SongLiKod/stararm-emulator-windows/releases/download/images` |
| 海外 | Hugging Face（官方） | `https://huggingface.co/datasets/SongLiKod/stararm-images/resolve/main` |

- 包体约定：`<镜像源>/aosp-13-arm64.zip`（zip 内含 `image.json`、`Image`、`system.img` 等，ARM64）。
- 默认「自动」：按国内优先顺序逐源尝试、失败自动回退，全部失败时给出逐源原因；设置里可固定某一条或填自定义 URL，并可「检测该源」在线确认是否已有镜像包（200 / 404 / 无法连接）。
- 发布镜像（发布一次即对相应源生效；镜像目录须含 `image.json`，位于镜像制作流水线/制品目录）：
  ```powershell
  ./build/publish_images.ps1 -ImageDir <本地镜像目录>   # 打包 + 上传 GitHub Release「images」(+ 可选 HuggingFace)
  ./build/publish_images.ps1 -ImageDir <本地镜像目录> -ZipOnly   # 只打包，先本地自测
  ./build/fetch_images.ps1                              # 从当前源拉取到本地
  ```
  - GitHub 凭据：本机 git 凭据管理器（`github.com`/`SongLiKod` 可写 token）自动读取，无需额外配置。
  - HuggingFace（`hf-mirror.com` / `huggingface.co` 两条源）：[新建 token](https://huggingface.co/settings/tokens)（勾选 **write**）→ `setx HF_TOKEN hf_xxx` → 重跑上面命令（或加 `-SkipHf` 跳过）；依赖 `pip install huggingface_hub`。

三种获取方式：

1. **内置源下载（GUI）**：新建实例 → 「下载所选内置镜像」（默认自动逐源尝试）。
2. **命令行 / 脚本**：`stararm-cli download-image --image aosp-13-arm64`、`./build/fetch_images.ps1`（均读取同一套源设置）。
3. **手动导入**：新建实例 → 「导入」，选择镜像 zip 或含 `image.json` 的目录（强制 ARM64 校验），导入后位于 `STARARM_HOME/mirror/images/`。

未选择镜像源或源暂无镜像包时，界面给出可读提示与逐源状态，而不是抛出原始异常栈。

## 打包部署

```powershell
./build/package.ps1 -WithQemu -WithAdb
# 产物：release/StarARM-win64-<version>.zip（绿色免配置，内置 QEMU + ADB）
```

PyInstaller 产物包含 GUI（`dist/StarARM/`，单目录绿色部署）与 CLI（`dist/stararm-cli.exe`，单文件），
语言包与主题随包内置。可选 Qt Installer Framework 安装包：

```powershell
binarycreator -c build/installer/config.xml -p build/installer/packages StarARMInstaller.exe
```

## CLI（无 GUI 后台运维）

```powershell
stararm-cli list                                                    # 列出实例
stararm-cli create --name my-vm --image aosp-13-arm64 --cpu 4 --mem 4 --disk 32
stararm-cli start --id my-vm --wait
stararm-cli batch-start / batch-stop / batch-delete / batch-configure --cpu 2
stararm-cli install --id my-vm --apk app.apk
stararm-cli push --id my-vm --local local.bin --remote /sdcard/x.bin
stararm-cli sync --id my-vm                          # 共享文件夹双向同步
stararm-cli adb-ports                                # 独立 ADB 端口（第三方工具可直连）
stararm-cli geo --id my-vm --lat 31.23 --lng 121.47
stararm-cli battery --id my-vm --level 55 --discharging
stararm-cli spoof --id my-vm --generate
stararm-cli macro --id my-vm --name my-macro         # 宏回放
stararm-cli config get [key] / config set <key> <value>
stararm-cli export --id my-vm --out out.zip / import-instance --zip out.zip
```

## 客户代理协议（virtio-serial）

QEMU 侧：`-chardev socket,...,host=127.0.0.1,port=<agent_port>,server=on,wait=off`
`-device virtserialport,...,name=stararm.agent`，JSON 行协议（每行一条）：

```json
{"cmd": "gps",          "lat": 39.9042, "lng": 116.4074}
{"cmd": "clipboard.set","text": "..."}
{"cmd": "clipboard.get"}
{"cmd": "imei.set",     "imei": "86..."}
{"cmd": "props.set",    "props": {"ro.product.model": "..."}}
-> {"ok": true, ...}
```

通道不可用时自动回退 ADB（setprop / settings put / dumpsys battery 等）。

## CI（GitHub Actions）

`.github/workflows/build.yml`（结构参照成熟 workflow）：

1. **test**（push/PR）：安装依赖并运行 `pytest`；
2. **windows**：`build/package.ps1 -WithQemu -WithAdb` 打包并上传 artifact；
3. **release**：推送 `v*` tag 或手动指定 version 时，创建 GitHub Release 并附带安装包。
