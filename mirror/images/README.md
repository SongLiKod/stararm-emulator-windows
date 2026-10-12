# 内置 ARM64 安卓镜像存储目录（Android 11-15）

本目录存放随部署包内置的标准 AOSP ARM64 镜像（`<id>/image.json` 清单 + 内核/系统镜像文件）。

镜像体积较大，不随 git 仓库分发，通过以下任一方式获取：

1. 内置源下载：GUI 新建实例点「下载所选内置镜像」（默认自动逐源尝试，国内优先，失败回退）；
2. 打包部署：运行 `build/fetch_images.ps1`（与 GUI 使用同一套源设置）；
3. 手动导入：GUI「导入镜像」或 CLI `stararm-cli import-image <目录或zip>`。

## 内置镜像源（resource/image_sources.json）

| 区域 | 源 | 基地址（下载 `<基地址>/<镜像ID>.zip`） |
| --- | --- | --- |
| 国内 | ghfast.top | `https://ghfast.top/https://github.com/SongLiKod/stararm-emulator-windows/releases/download/images` |
| 国内 | hf-mirror.com | `https://hf-mirror.com/datasets/SongLiKod/stararm-images/resolve/main` |
| 海外 | GitHub Releases | `https://github.com/SongLiKod/stararm-emulator-windows/releases/download/images` |
| 海外 | Hugging Face | `https://huggingface.co/datasets/SongLiKod/stararm-images/resolve/main` |

发布镜像包（两个源组一次搞定）：

```powershell
# 镜像目录须含 image.json（读取其 id 决定 zip 名）
./build/publish_images.ps1 -ImageDir <镜像目录>            # 打包 + 上传 GitHub Release「images」+ HuggingFace
./build/publish_images.ps1 -ImageDir <镜像目录> -SkipHf    # 只发 GitHub（ghfast.top 随即可用）
```

- GitHub：自动读取本机 git 凭据管理器中的 `github.com` 可写 token，无需配置。
- HuggingFace（`hf-mirror.com` / `huggingface.co`）：https://huggingface.co/settings/tokens 新建 **write** 权限 token → `setx HF_TOKEN hf_xxx` → 重跑脚本；依赖 `pip install huggingface_hub`（可用 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 加速）。

## 内置镜像定义

| 镜像 ID | 安卓版本 | 架构 |
| --- | --- | --- |
| aosp-11-arm64 | Android 11 | arm64-v8a |
| aosp-12-arm64 | Android 12 | arm64-v8a |
| aosp-13-arm64 | Android 13 | arm64-v8a |
| aosp-14-arm64 | Android 14 | arm64-v8a |
| aosp-15-arm64 | Android 15 | arm64-v8a |

## 镜像清单格式（image.json）

```json
{
  "id": "aosp-13-arm64",
  "name": "AOSP 13 (ARM64)",
  "android_version": 13,
  "arch": "arm64-v8a",
  "kernel": "Image",
  "ramdisk": "ramdisk.img",
  "cmdline": "console=ttyAMA0,38400 root=/dev/vda1 rw androidboot.hardware=stararm",
  "drives": [{"file": "system.img", "format": "raw", "id": "system", "base": "true"}]
}
```

镜像基于 AOSP 标准 arm64 构建（userdebug，内置 stararm-agent 串口守护进程与 adbd TCP 支持），
无魔改、无转译，纯原生 ARM 指令执行，与真实手机架构完全一致。
