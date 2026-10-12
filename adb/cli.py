"""StarARM CLI 命令行工具：无 GUI 后台运维、批量自动化操作（输出双语）。

用法：
    python -m adb.cli <命令> [参数]
    stararm-cli <命令> [参数]   （PyInstaller 打包后）
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional

from adb.adb_manager import AdbError
from config.i18n import get_translator
from config.settings import SettingsManager
from core.instance import InstanceConfig
from core.service import StarARMService
from log.logger import get_logger
from mirror.image_manager import ImageManager, ImageManagerError
from tools import clipboard as clipboard_tool
from tools import device_profile as profile_tool
from tools import file_sync as sync_tool
from tools.recorder import ScreenRecorder
from tools.screenshot import capture_screenshot

T = get_translator()


def p(key: str, **params) -> None:
    print(T.tr(key, **params))


def fail(key: str, detail: str = "", code: int = 1) -> int:
    text = T.tr(key)
    if detail:
        print(f"{text}\n  {detail}")
    else:
        print(text)
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stararm-cli",
        description=T.tr("cli_desc"),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # list
    sp = sub.add_parser("list", aliases=["ls"], help=T.tr("cli_list_help"))
    sp.add_argument("--json", action="store_true", help="JSON output")

    # create
    sp = sub.add_parser("create", help=T.tr("cli_create_help"))
    sp.add_argument("--name", required=True, help=T.tr("cli_arg_name"))
    sp.add_argument("--image", default="aosp-13-arm64", help=T.tr("cli_arg_image"))
    sp.add_argument("--cpu", type=int, default=None, help=T.tr("cli_arg_cpu"))
    sp.add_argument("--mem", type=int, default=None, help=T.tr("cli_arg_mem"))
    sp.add_argument("--disk", type=int, default=None, help=T.tr("cli_arg_disk"))
    sp.add_argument("--resolution", default=None, help=T.tr("cli_arg_resolution"))
    sp.add_argument("--dpi", type=int, default=None, help=T.tr("cli_arg_dpi"))
    sp.add_argument("--net", choices=["nat", "bridge"], default=None, help=T.tr("cli_arg_net"))

    # clone / copy
    for cmd, help_key in (("clone", "cli_clone_help"), ("copy", "cli_copy_help")):
        sp = sub.add_parser(cmd, help=T.tr(help_key))
        sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
        sp.add_argument("--name", default=None, help=T.tr("cli_arg_new_name"))

    # delete
    sp = sub.add_parser("delete", aliases=["rm"], help=T.tr("cli_delete_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--force", action="store_true", help=T.tr("cli_arg_force"))

    # start / stop
    sp = sub.add_parser("start", help=T.tr("cli_start_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--wait", action="store_true", help=T.tr("cli_arg_wait"))
    sp = sub.add_parser("stop", help=T.tr("cli_stop_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--force", action="store_true", help=T.tr("cli_arg_force"))

    # batch
    for cmd, help_key in (
        ("batch-start", "cli_batch_start_help"),
        ("batch-stop", "cli_batch_stop_help"),
        ("batch-delete", "cli_batch_delete_help"),
    ):
        sp = sub.add_parser(cmd, help=T.tr(help_key))
        sp.add_argument("--ids", nargs="*", default=None, help=T.tr("cli_arg_ids"))
        if cmd == "batch-delete":
            sp.add_argument("--force", action="store_true", help=T.tr("cli_arg_force"))
    sp = sub.add_parser("batch-configure", help=T.tr("cli_batch_configure_help"))
    sp.add_argument("--ids", nargs="*", default=None, help=T.tr("cli_arg_ids"))
    sp.add_argument("--cpu", type=int, default=None, help=T.tr("cli_arg_cpu"))
    sp.add_argument("--mem", type=int, default=None, help=T.tr("cli_arg_mem"))
    sp.add_argument("--disk", type=int, default=None, help=T.tr("cli_arg_disk"))

    # export / import / backup / restore
    sp = sub.add_parser("export", help=T.tr("cli_export_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--out", required=True, help=T.tr("cli_arg_out"))
    sp = sub.add_parser("import-instance", help=T.tr("cli_import_instance_help"))
    sp.add_argument("--zip", required=True, help=T.tr("cli_arg_zip"))
    sp.add_argument("--name", default=None, help=T.tr("cli_arg_new_name"))
    sp = sub.add_parser("backup", help=T.tr("cli_backup_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp = sub.add_parser("restore", help=T.tr("cli_restore_help"))
    sp.add_argument("--zip", required=True, help=T.tr("cli_arg_zip"))
    sp.add_argument("--name", default=None, help=T.tr("cli_arg_new_name"))

    # image management
    sp = sub.add_parser("images", help=T.tr("cli_images_help"))
    sp = sub.add_parser("import-image", help=T.tr("cli_import_image_help"))
    sp.add_argument("--src", required=True, help=T.tr("cli_arg_src"))
    sp = sub.add_parser("export-image", help=T.tr("cli_export_image_help"))
    sp.add_argument("--image", required=True, help=T.tr("cli_arg_image"))
    sp.add_argument("--out", required=True, help=T.tr("cli_arg_out"))
    sp = sub.add_parser("download-image", help=T.tr("cli_download_image_help"))
    sp.add_argument("--image", required=True, help=T.tr("cli_arg_image"))

    # adb
    sp = sub.add_parser("install", help=T.tr("cli_install_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--apk", required=True, help=T.tr("cli_arg_apk"))
    sp = sub.add_parser("push", help=T.tr("cli_push_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--local", required=True, help=T.tr("cli_arg_local"))
    sp.add_argument("--remote", required=True, help=T.tr("cli_arg_remote"))
    sp = sub.add_parser("pull", help=T.tr("cli_pull_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--remote", required=True, help=T.tr("cli_arg_remote"))
    sp.add_argument("--local", required=True, help=T.tr("cli_arg_local"))
    sp = sub.add_parser("sync", help=T.tr("cli_sync_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp = sub.add_parser("shell", help=T.tr("cli_shell_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("command", nargs=argparse.REMAINDER, help=T.tr("cli_arg_cmd"))
    sp = sub.add_parser("adb-ports", help=T.tr("cli_adb_ports_help"))

    # tools
    sp = sub.add_parser("screenshot", help=T.tr("cli_screenshot_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--out", default=None, help=T.tr("cli_arg_outdir"))
    sp = sub.add_parser("record", help=T.tr("cli_record_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--seconds", type=int, default=30, help=T.tr("cli_arg_seconds"))
    sp.add_argument("--out", default=None, help=T.tr("cli_arg_outdir"))
    sp = sub.add_parser("geo", help=T.tr("cli_geo_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--lat", type=float, required=True, help=T.tr("cli_arg_lat"))
    sp.add_argument("--lng", type=float, required=True, help=T.tr("cli_arg_lng"))
    sp = sub.add_parser("battery", help=T.tr("cli_battery_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--level", type=int, default=None, help=T.tr("cli_arg_level"))
    sp.add_argument("--charging", dest="charging", action="store_true", help=T.tr("cli_arg_charging"))
    sp.add_argument("--discharging", dest="charging", action="store_false", help=T.tr("cli_arg_discharging"))
    sp.set_defaults(charging=True)
    sp = sub.add_parser("spoof", help=T.tr("cli_spoof_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--brand", default=None, help=T.tr("cli_arg_brand"))
    sp.add_argument("--model", default=None, help=T.tr("cli_arg_model"))
    sp.add_argument("--serial", default=None, help=T.tr("cli_arg_serialno"))
    sp.add_argument("--imei", default=None, help=T.tr("cli_arg_imei"))
    sp.add_argument("--android-id", default=None, help=T.tr("cli_arg_android_id"))
    sp.add_argument("--fingerprint", default=None, help=T.tr("cli_arg_fingerprint"))
    sp.add_argument("--generate", action="store_true", help=T.tr("cli_arg_generate"))
    sp = sub.add_parser("macro", help=T.tr("cli_macro_help"))
    sp.add_argument("--id", required=True, help=T.tr("cli_arg_id"))
    sp.add_argument("--name", required=True, help=T.tr("cli_arg_macro_name"))

    # config
    sp = sub.add_parser("config", help=T.tr("cli_config_help"))
    sp.add_argument("action", choices=["get", "set"], help=T.tr("cli_arg_action"))
    sp.add_argument("key", nargs="?", default=None, help=T.tr("cli_arg_key"))
    sp.add_argument("value", nargs="?", default=None, help=T.tr("cli_arg_value"))
    sp = sub.add_parser("version", help=T.tr("cli_version_help"))

    return parser


# --------------------------------------------------------------------- helpers
def _resolve(service: StarARMService, id_or_name: str):
    inst = service.instances.resolve(id_or_name)
    if inst is None:
        raise SystemExit(fail("err_instance_not_found", id_or_name, code=2))
    return inst


def _running(service: StarARMService, ids: Optional[List[str]]) -> List:
    if ids is not None:
        return [_resolve(service, i) for i in ids]
    return [i for i in service.instances.list_instances() if i.state == "running"]


def _guest_agent(service: StarARMService, inst):
    from core.guest_agent import GuestAgentClient
    return GuestAgentClient(port=inst.config.agent_port)


# --------------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    service = StarARMService()
    log = get_logger()
    cmd = args.command
    instances = service.instances

    try:
        if cmd in ("list", "ls"):
            items = instances.list_instances()
            if args.json:
                import json as _json
                print(_json.dumps(
                    [{
                        "id": i.id, "name": i.name, "state": i.state,
                        "image": i.image_id, "cpu": i.config.cpu_cores,
                        "mem_mb": i.config.memory_mb, "disk_gb": i.config.disk_gb,
                        "adb_port": i.config.adb_port,
                        "resolution": i.config.resolution, "dpi": i.config.dpi,
                    } for i in items], ensure_ascii=False, indent=2))
                return 0
            if not items:
                p("msg_no_instance")
                return 0
            p("cli_list_header")
            for i in items:
                state = T.tr(f"state_{i.state}")
                print(f"  {i.id}  {i.name:16}  {state:8}  {i.image_id:16} "
                      f"CPU={i.config.cpu_cores} MEM={i.config.memory_mb}MB "
                      f"ADB=127.0.0.1:{i.config.adb_port}")
            return 0

        if cmd == "create":
            cfg = InstanceConfig()
            if args.cpu:
                cfg.cpu_cores = args.cpu
            if args.mem:
                cfg.memory_mb = args.mem
            if args.disk:
                cfg.disk_gb = args.disk
            if args.resolution:
                cfg.resolution = args.resolution
            if args.dpi:
                cfg.dpi = args.dpi
            if args.net:
                cfg.network_mode = args.net
            inst = instances.create(args.name, args.image, cfg)
            p("msg_create_success", id=inst.id, name=inst.name, port=inst.config.adb_port)
            return 0

        if cmd == "clone":
            inst = instances.clone(args.id, args.name)
            p("msg_clone_success", name=inst.name, id=inst.id)
            return 0

        if cmd == "copy":
            inst = instances.copy(args.id, args.name)
            p("msg_copy_success", name=inst.name, id=inst.id)
            return 0

        if cmd in ("delete", "rm"):
            instances.delete(args.id, force=args.force)
            p("msg_delete_success", id=args.id)
            return 0

        if cmd == "start":
            inst = _resolve(service, args.id)
            if inst.state == "running":
                p("msg_already_running", id=inst.name)
                return 0
            instances.start(inst.id, wait=args.wait)
            if args.wait:
                p("msg_start_success", id=inst.name)
            else:
                p("msg_start_async", id=inst.name)
            return 0

        if cmd == "stop":
            inst = _resolve(service, args.id)
            instances.stop(inst.id, force=args.force, wait=True)
            p("msg_stop_success", id=inst.name)
            return 0

        if cmd == "batch-start":
            targets = _running(service, None) if args.ids is None else \
                [_resolve(service, i) for i in args.ids]
            if not targets:
                p("msg_no_instance")
                return 0
            results = instances.batch_start([i.id for i in targets])
            p("msg_batch_done", ok=sum(1 for _, okk, _ in results if okk),
              fail=sum(1 for _, okk, _ in results if not okk))
            return 0 if all(okk for _, okk, _ in results) else 1

        if cmd == "batch-stop":
            targets = _running(service, args.ids)
            if not targets:
                p("msg_no_running_instance")
                return 0
            results = instances.batch_stop([i.id for i in targets], force=args.force)
            p("msg_batch_done", ok=sum(1 for _, okk, _ in results if okk),
              fail=sum(1 for _, okk, _ in results if not okk))
            return 0

        if cmd == "batch-delete":
            targets = [i for i in instances.list_instances()
                       if args.ids is None or i.id in args.ids or i.name in args.ids]
            if not targets:
                p("msg_no_instance")
                return 0
            results = instances.batch_delete([i.id for i in targets], force=args.force)
            p("msg_batch_done", ok=sum(1 for _, okk, _ in results if okk),
              fail=sum(1 for _, okk, _ in results if not okk))
            return 0

        if cmd == "batch-configure":
            targets = [i for i in instances.list_instances()
                       if args.ids is None or i.id in args.ids or i.name in args.ids]
            if not targets:
                p("msg_no_instance")
                return 1
            fields = {}
            if args.cpu:
                fields["cpu_cores"] = args.cpu
            if args.mem:
                fields["memory_mb"] = args.mem
            if args.disk:
                fields["disk_gb"] = args.disk
            if not fields:
                return fail("cli_msg_no_fields", "", code=2)
            results = instances.batch_configure([i.id for i in targets], **fields)
            p("msg_batch_done", ok=sum(1 for _, okk, _ in results if okk),
              fail=sum(1 for _, okk, _ in results if not okk))
            return 0

        if cmd == "export":
            path = instances.export_instance(args.id, Path(args.out))
            p("msg_export_success", path=str(path))
            return 0

        if cmd == "import-instance":
            inst = instances.import_instance(Path(args.zip), args.name)
            p("msg_import_instance_success", name=inst.name, id=inst.id)
            return 0

        if cmd == "backup":
            path = instances.backup(args.id)
            p("msg_backup_success", path=str(path))
            return 0

        if cmd == "restore":
            inst = instances.restore(Path(args.zip), args.name)
            p("msg_restore_success", name=inst.name, id=inst.id)
            return 0

        if cmd == "images":
            images = service.images.list_images()
            p("cli_images_header")
            for img in images:
                status = T.tr("msg_image_ready") if img.is_ready else T.tr("msg_image_missing")
                print(f"  {img.id:20} Android {img.android_version:<3} "
                      f"arch={img.manifest.arch:10} {status}")
            return 0

        if cmd == "import-image":
            img = service.images.import_image(Path(args.src))
            p("msg_image_imported", id=img.id)
            return 0

        if cmd == "export-image":
            path = service.images.export_image(args.image, Path(args.out))
            p("msg_image_exported", path=str(path))
            return 0

        if cmd == "download-image":
            service.images.download_builtin(args.image)
            p("msg_image_imported", id=args.image)
            return 0

        if cmd == "install":
            inst = _resolve(service, args.id)
            if inst.state != "running":
                return fail("err_instance_not_running", "", code=2)
            service.adb.connect(inst.config.adb_port)
            service.adb.install(inst.config.adb_port, args.apk)
            p("msg_install_success")
            return 0

        if cmd == "push":
            inst = _resolve(service, args.id)
            ok = sync_tool.push_file(service.adb, inst.config.adb_port,
                                     args.local, args.remote)
            return 0 if ok else fail("err_transfer_failed", "", code=1)

        if cmd == "pull":
            inst = _resolve(service, args.id)
            ok = sync_tool.pull_file(service.adb, inst.config.adb_port,
                                     args.remote, args.local)
            return 0 if ok else fail("err_transfer_failed", "", code=1)

        if cmd == "sync":
            inst = _resolve(service, args.id)
            sf = sync_tool.default_sync(service.adb, service.settings)
            pushed, pulled = sf.sync_bidirectional(inst.config.adb_port)
            p("msg_sync_done", pushed=pushed, pulled=pulled)
            return 0

        if cmd == "shell":
            inst = _resolve(service, args.id)
            command = " ".join(args.command).strip() or "true"
            out = service.adb.shell(inst.config.adb_port, command)
            print(out)
            return 0

        if cmd == "adb-ports":
            p("cli_adb_ports_header")
            for i in instances.list_instances():
                print(f"  {i.name:16} 127.0.0.1:{i.config.adb_port} ({T.tr(f'state_{i.state}')})")
            return 0

        if cmd == "screenshot":
            inst = _resolve(service, args.id)
            if inst.state != "running":
                return fail("err_instance_not_running", "", code=2)
            path = capture_screenshot(service.adb, inst.config.adb_port, inst.name,
                                      Path(args.out) if args.out else None)
            p("msg_screenshot_saved", path=str(path))
            return 0

        if cmd == "record":
            inst = _resolve(service, args.id)
            if inst.state != "running":
                return fail("err_instance_not_running", "", code=2)
            rec = ScreenRecorder(service.adb)
            rec.start(inst.config.adb_port, inst.name, args.seconds)
            p("msg_recording")
            path = rec.stop(Path(args.out) if args.out else None)
            p("msg_record_saved", path=str(path))
            return 0

        if cmd == "geo":
            inst = _resolve(service, args.id)
            if inst.state != "running":
                return fail("err_instance_not_running", "", code=2)
            instances.update_config(inst.id, **{
                "gps.latitude": args.lat, "gps.longitude": args.lng})
            agent = _guest_agent(service, inst)
            ok = agent.set_gps(args.lat, args.lng)
            return 0 if ok else fail("err_agent_unavailable", "", code=1)

        if cmd == "battery":
            inst = _resolve(service, args.id)
            if inst.state != "running":
                return fail("err_instance_not_running", "", code=2)
            level = args.level if args.level is not None else inst.config.battery.level
            instances.update_config(inst.id, **{
                "battery.level": level, "battery.charging": args.charging})
            ok = service.adb.battery_set(inst.config.adb_port, level, args.charging)
            return 0 if ok else fail("err_battery_failed", "", code=1)

        if cmd == "spoof":
            inst = _resolve(service, args.id)
            if inst.state != "running":
                return fail("err_instance_not_running", "", code=2)
            if args.generate:
                inst.config.device = profile_tool.generate_profile()
            if args.brand:
                inst.config.device.brand = args.brand
                inst.config.device.manufacturer = args.brand
            if args.model:
                inst.config.device.model = args.model
            if args.serial:
                inst.config.device.serial = args.serial
            if args.imei:
                inst.config.device.imei = args.imei
            if args.android_id:
                inst.config.device.android_id = args.android_id
            if args.fingerprint:
                inst.config.device.fingerprint = args.fingerprint
            instances.save(inst)
            agent = _guest_agent(service, inst)
            image = service.images.get(inst.image_id)
            version = image.android_version if image else 13
            report = profile_tool.apply_profile(service.adb, agent, inst.config, version)
            ok_items = sum(1 for _, okk in report if okk)
            p("msg_spoof_applied", ok=ok_items, total=len(report))
            return 0

        if cmd == "macro":
            from tools.macro import Macro, MacroRunner
            inst = _resolve(service, args.id)
            if inst.state != "running":
                return fail("err_instance_not_running", "", code=2)
            macro = Macro.load(args.name)
            if macro is None:
                return fail("err_macro_not_found", args.name, code=2)
            service.adb.connect(inst.config.adb_port)
            executed = MacroRunner(service.adb, inst.config.adb_port).run(macro)
            p("msg_macro_done", steps=executed)
            return 0

        if cmd == "config":
            settings: SettingsManager = service.settings
            s = settings.get()
            if args.action == "get":
                import dataclasses
                data = dataclasses.asdict(s)
                if args.key:
                    if args.key not in data:
                        return fail("err_config_key", args.key, code=2)
                    print(f"{args.key} = {data[args.key]}")
                else:
                    for k, v in data.items():
                        print(f"{k} = {v}")
                return 0
            if args.action == "set":
                if not args.key or args.value is None:
                    return fail("cli_msg_config_usage", "", code=2)
                key = args.key
                current = getattr(s, key, None)
                if current is None:
                    return fail("err_config_key", key, code=2)
                value = args.value
                if isinstance(current, bool):
                    value = str(value).lower() in ("1", "true", "yes", "on")
                elif isinstance(current, int):
                    value = int(value)
                settings.update(**{key: value})
                p("msg_config_saved")
                return 0

        if cmd == "version":
            from config.constants import APP_NAME_ZH, APP_NAME_EN, VERSION
            print(f"{APP_NAME_ZH} ({APP_NAME_EN}) v{VERSION}")
            return 0

        parser.print_help()
        return 0

    except (AdbError, ImageManagerError) as exc:
        return fail(exc.key, getattr(exc, "detail", ""), code=1)
    except KeyError as exc:
        return fail("err_instance_not_found", str(exc), code=2)
    except RuntimeError as exc:
        key = getattr(exc, "key", None)
        if key:
            return fail(key, str(getattr(exc, "detail", "")) or "", code=1)
        return fail("err_unknown", str(exc), code=1)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        log.error("err_unknown", detail=str(exc)[:300])
        return fail("err_unknown", str(exc), code=1)


def run() -> int:
    return main()


if __name__ == "__main__":
    raise SystemExit(main())
