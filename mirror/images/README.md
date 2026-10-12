# 内置 ARM64 安卓镜像存储目录（Android 11-15）

本目录存放随部署包内置的标准 AOSP ARM64 镜像（`<id>/image.json` 清单 + 内核/系统镜像文件）。

镜像体积较大，不随 git 仓库分发，通过以下任一方式获取：

1. 打包部署：运行 `build/fetch_images.ps1`（从全局设置的镜像源下载）；
2. 手动导入：GUI「导入镜像」或 CLI `stararm-cli import-image <目录或zip>`；
3. 镜像源下载：全局设置「镜像源 URL」+ GUI 新建实例时按需下载。

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
