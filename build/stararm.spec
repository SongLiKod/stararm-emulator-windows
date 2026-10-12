# -*- mode: python ; coding: utf-8 -*-
"""星模ARM原生安卓模拟器 PyInstaller 打包配置。

产物：
- dist/StarARM/        GUI（Qt 6.5 / PySide6，单目录绿色部署，免配置）
- dist/stararm-cli.exe CLI（无 GUI 后台运维，单文件）
resource/（语言包、主题配色、图标）随包内置。
"""
import os
import re

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))


def _version() -> str:
    try:
        with open(os.path.join(ROOT, "config", "constants.py"),
                  encoding="utf-8") as f:
            text = f.read()
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "1.0.0"


VERSION = _version()
RESOURCE = os.path.join(ROOT, "resource")

# ---------------------------------------------------------------- GUI
gui = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(RESOURCE, "resource")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz_gui = PYZ(gui.pure)

exe_gui = EXE(
    pyz_gui,
    gui.scripts,
    [],
    exclude_binaries=True,
    name="StarARM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=None,
)
coll = COLLECT(
    exe_gui,
    gui.binaries,
    gui.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StarARM",
)

# ---------------------------------------------------------------- CLI
cli = Analysis(
    [os.path.join(ROOT, "adb", "cli.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(RESOURCE, "resource")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz_cli = PYZ(cli.pure)

exe_cli = EXE(
    pyz_cli,
    cli.scripts,
    [],
    exclude_binaries=False,
    name="stararm-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    version=None,
)
