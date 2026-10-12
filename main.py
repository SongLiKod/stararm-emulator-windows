"""星模ARM原生安卓模拟器（StarARM Emulator）- GUI 入口。

纯 ARM64（aarch64）原生架构安卓模拟器：QEMU 整机仿真 + Qt 6.5 GUI。
CLI（无界面后台运维）入口：python -m adb.cli
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.app import run  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run())
