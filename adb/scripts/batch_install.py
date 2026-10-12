#!/usr/bin/env python3
"""StarARM 批量安装自动化脚本示例：对全部运行中实例批量安装 APK。

用法（配合 CLI）：
    python adb/scripts/batch_install.py --apk path/to/app.apk [--ids id1 id2]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config.i18n import get_translator  # noqa: E402
from core.service import StarARMService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="StarARM batch install")
    parser.add_argument("--apk", required=True, help="APK file path")
    parser.add_argument("--ids", nargs="*", default=None, help="instance ids (default: running)")
    args = parser.parse_args()

    service = StarARMService()
    trans = get_translator()
    instances = service.instances.list_instances()
    if args.ids is not None:
        targets = [i for i in instances if i.id in args.ids]
    else:
        targets = [i for i in instances if i.state == "running"]
    if not targets:
        print(trans.tr("msg_no_running_instance"))
        return 1
    for inst in targets:
        try:
            service.adb.connect(inst.config.adb_port)
            service.adb.install(inst.config.adb_port, args.apk)
            print(f"[{inst.name}] {trans.tr('msg_install_success')}")
        except Exception as exc:
            print(f"[{inst.name}] {trans.tr('msg_install_failed')}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
