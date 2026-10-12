"""QEMU-aarch64 调度核心：纯 ARM64 整机仿真（禁用一切 X86 转译组件）。

核心要点：
- qemu-system-aarch64 完整仿真 ARM64 CPU/内存/总线/外设，原生执行 ARM 指令
- 虚拟化加速：WHPX（KVM-like Windows 加速）不可用时自动降级 TCG 并提示
- 图形加速：VirGL（OpenGL ES / Vulkan via Venus）不可用时自动降级并提示
- 每实例独立：CPU/内存/磁盘 qcow2 覆盖层、ADB 端口、VNC 显示端口、客户代理端口
- NAT / 桥接双网络模式；内置镜像 + 用户自定义镜像
"""
import os
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Tuple

from adb.adb_manager import AdbManager, CREATE_NO_WINDOW
from config.settings import SettingsManager
from core.guest_agent import GuestAgentClient
from core.instance import Instance, InstanceConfig, InstanceState
from core.qemu_errors import classify_qemu_error, is_graphics_error
from core.resource_guard import ResourceGuard
from core.virtualization import VirtualizationStatus, detect_virtualization
from log.logger import get_logger
from mirror.image import AndroidImage
from mirror.image_manager import ImageManager
from tools.device_profile import apply_profile

# 图形加速降级链
GRAPHICS_DOWNGRADE = {"virgl-vulkan": "virgl", "virgl": "software"}
EARLY_EXIT_WINDOW_S = 12
BOOT_TIMEOUT_S = 300
STATE_FILE = "qemu.pid"

Listener = Callable[[str, str, str, str], None]  # (instance_id, state, error_key, detail)


def _host_without_drive(path: Path) -> str:
    """QEMU -drive file= 在 Windows 上对盘符路径的兼容处理。"""
    return str(path)


class _PipeReader(threading.Thread):
    """持续读取子进程管道，避免 QEMU 输出阻塞管道，并保留尾部日志。"""

    def __init__(self, pipe, buf: Deque[str], maxlen: int = 80) -> None:
        super().__init__(daemon=True)
        self._pipe = pipe
        self._buf = buf
        self._maxlen = maxlen

    def run(self) -> None:
        try:
            for line in iter(self._pipe.readline, b""):
                try:
                    text = line.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    continue
                self._buf.append(text)
                if len(self._buf) > self._maxlen:
                    self._buf.popleft()
        except Exception:
            pass


class QemuManager:
    """QEMU 进程调度管理。"""

    def __init__(
        self,
        settings: SettingsManager,
        images: ImageManager,
        adb: AdbManager,
        guard: ResourceGuard,
    ) -> None:
        self._settings = settings
        self._images = images
        self._adb = adb
        self._guard = guard
        self._vt: Optional[VirtualizationStatus] = None
        self._vt_at = 0.0
        self._lock = threading.RLock()
        self._runtime: Dict[str, dict] = {}
        self._listeners: List[Listener] = []
        self._stopping = set()
        # 由服务层注入：端口变更持久化回调（实例配置写盘）
        self.save_instance_config: Optional[Callable[[Instance], None]] = None

    # ------------------------------------------------------------- signals
    def add_listener(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def _notify(self, instance_id: str, state: str, error_key: str = "", detail: str = "") -> None:
        for cb in list(self._listeners):
            try:
                cb(instance_id, state, error_key, detail)
            except Exception:
                pass

    # ------------------------------------------------------------- locate
    def locate_qemu(self) -> Optional[str]:
        candidates: List[Path] = []
        s = self._settings.get()
        if s.qemu_path:
            p = Path(s.qemu_path)
            if p.is_dir():
                candidates.append(p / ("qemu-system-aarch64.exe" if os.name == "nt" else "qemu-system-aarch64"))
            else:
                candidates.append(p)
        exe_name = "qemu-system-aarch64.exe" if os.name == "nt" else "qemu-system-aarch64"
        import sys
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "qemu" / exe_name)
        else:
            candidates.append(Path(__file__).resolve().parent.parent / "qemu-runtime" / exe_name)
        which = subprocess.run(
            ["where" if os.name == "nt" else "which", exe_name],
            capture_output=True, text=True, timeout=10, creationflags=CREATE_NO_WINDOW,
        ) if os.name == "nt" else None
        if which and which.returncode == 0:
            for line in (which.stdout or "").splitlines():
                line = line.strip()
                if line:
                    candidates.append(Path(line))
        import shutil
        found = shutil.which(exe_name)
        if found:
            candidates.append(Path(found))
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

    def locate_qemu_img(self) -> Optional[str]:
        qemu = self.locate_qemu()
        if not qemu:
            return None
        img = Path(qemu).parent / ("qemu-img.exe" if os.name == "nt" else "qemu-img")
        return str(img) if img.is_file() else None

    # ------------------------------------------------------------- vt
    def virtualization(self, refresh: bool = False) -> VirtualizationStatus:
        if refresh or self._vt is None or time.time() - self._vt_at > 60:
            self._vt = detect_virtualization()
            self._vt_at = time.time()
        return self._vt

    # ------------------------------------------------------------- runtime
    def runtime(self, instance_id: str) -> Optional[dict]:
        return self._runtime.get(instance_id)

    def is_running(self, instance_id: str) -> bool:
        with self._lock:
            rt = self._runtime.get(instance_id)
            if rt:
                proc = rt.get("proc")
                if proc is not None and proc.poll() is None:
                    return True
            pid = self._read_pid(instance_id)
            return pid is not None and _pid_alive(pid)

    def _read_pid(self, instance_id: str) -> Optional[int]:
        f = self._pid_file(instance_id)
        try:
            return int(f.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _pid_file(self, instance_id: str) -> Path:
        return Path(self._data_dir(instance_id)) / STATE_FILE

    def _data_dir(self, instance_id: str) -> str:
        from config import paths
        return str(paths.instance_dir(instance_id))

    def sync_runtime_state(self, instances: List[Instance]) -> None:
        """GUI 启动 / CLI 启动时同步：按 pidfile 恢复运行状态。"""
        for inst in instances:
            if inst.id in self._stopping:
                inst.state = InstanceState.STOPPING
                continue
            if self.is_running(inst.id):
                pid = self._read_pid(inst.id) or 0
                with self._lock:
                    self._runtime.setdefault(inst.id, {
                        "proc": None, "pid": pid,
                        "adb_port": inst.config.adb_port,
                        "vnc_display": inst.config.vnc_display,
                        "agent_port": inst.config.agent_port,
                    })
                inst.state = InstanceState.RUNNING
            else:
                if inst.state in (InstanceState.RUNNING, InstanceState.STARTING):
                    inst.state = InstanceState.STOPPED
                self._runtime.pop(inst.id, None)

    # ------------------------------------------------------------- start
    def start(self, instance: Instance, wait: bool = False) -> None:
        """启动实例（后台线程）。wait=True 时阻塞等待至运行或失败。"""
        done = threading.Event()
        t = threading.Thread(target=self._start_flow, args=(instance, done), daemon=True)
        t.start()
        if wait:
            done.wait(BOOT_TIMEOUT_S + 60)

    def _start_flow(self, instance: Instance, done: threading.Event) -> None:
        log = get_logger()
        try:
            with self._lock:
                if self.is_running(instance.id):
                    return
            qemu_bin = self.locate_qemu()
            if not qemu_bin:
                instance.state = InstanceState.ERROR
                instance.last_error = "err_qemu_not_found"
                instance.last_error_detail = ""
                log.error("err_qemu_not_found", id=instance.name)
                self._notify(instance.id, InstanceState.ERROR, "err_qemu_not_found", "")
                return
            try:
                image = self._images.get_ready(instance.image_id)
            except Exception as exc:
                key = getattr(exc, "key", "err_image_not_found")
                instance.state = InstanceState.ERROR
                instance.last_error = key
                instance.last_error_detail = getattr(exc, "detail", str(exc))
                log.error(key, id=instance.name, detail=instance.last_error_detail[:200])
                self._notify(instance.id, InstanceState.ERROR, key, instance.last_error_detail)
                return

            # 端口冲突时重新分配（导入的实例可能端口冲突）
            ports_ok = self._ensure_ports(instance)
            if not ports_ok:
                self._fail(instance, "err_no_free_port", "")
                return

            # 资源超限保护：运行中实例 CPU/内存合计 + 新实例不得超过全局阈值
            running_cfgs = []
            for inst in self._all_instances():
                if inst.id != instance.id and self.is_running(inst.id):
                    running_cfgs.append((inst.config.cpu_cores, inst.config.memory_mb))
            ok, reason = self._guard.check_start(
                instance.config.cpu_cores, instance.config.memory_mb, running_cfgs,
            )
            if not ok:
                self._fail(instance, reason, "")
                return

            # 磁盘：root = 实例 CoW overlay（backing=镜像基盘，rw），/data = 独立 qcow2
            data_dir = Path(self._data_dir(instance.id))
            overlay = data_dir / "overlay.qcow2"
            data_disk = data_dir / "data.qcow2"
            try:
                self._ensure_overlay(overlay, image)
                self._ensure_data_disk(data_disk, instance.config.disk_gb)
            except Exception as exc:
                self._fail(instance, "err_disk", str(exc)[:300])
                return

            vt = self.virtualization()
            accel = vt.method
            if accel == "tcg":
                log.system("log_vt_degraded", level="WARNING", id=instance.name)

            graphics = instance.config.graphics
            attempt = 0
            while True:
                args = self.build_args(instance, image, accel=accel, graphics=graphics,
                                       overlay=overlay, data_disk=data_disk)
                instance.state = InstanceState.STARTING
                self._notify(instance.id, InstanceState.STARTING, "", "")
                log.run("log_instance_starting", id=instance.name, accel=accel, graphics=graphics)
                proc, stderr_buf, stdout_buf = self._spawn(qemu_bin, args)
                with self._lock:
                    self._runtime[instance.id] = {
                        "proc": proc, "pid": proc.pid,
                        "adb_port": instance.config.adb_port,
                        "vnc_display": instance.config.vnc_display,
                        "agent_port": instance.config.agent_port,
                    }
                try:
                    self._pid_file(instance.id).write_text(str(proc.pid), encoding="utf-8")
                except OSError:
                    pass
                exited = self._wait_early_exit(proc, EARLY_EXIT_WINDOW_S)
                if exited is None:
                    break  # 存活 -> 进入引导等待
                # 早期退出：按错误类别自动降级重试
                stderr_text = "\n".join(stderr_buf)
                error_key = classify_qemu_error(stderr_text)
                attempt += 1
                if is_graphics_error(error_key, stderr_text) and graphics in GRAPHICS_DOWNGRADE:
                    degraded = GRAPHICS_DOWNGRADE[graphics]
                    log.run("log_graphics_degraded", level="WARNING",
                            id=instance.name, graphics=degraded)
                    instance.config.graphics = degraded
                    self._persist_config(instance)
                    graphics = degraded
                    continue
                if error_key == "err_virtualization" and accel != "tcg":
                    accel = "tcg"
                    log.run("log_accel_degraded", level="WARNING", id=instance.name, accel=accel)
                    continue
                if error_key == "err_port":
                    ports_ok = self._ensure_ports(instance, force=True)
                    if ports_ok and attempt < 3:
                        continue
                with self._lock:
                    self._runtime.pop(instance.id, None)
                self._fail(instance, error_key, stderr_text)
                return

            # 引导等待 + 开机后应用硬件模拟参数
            self._adb.start_server()
            self._notify(instance.id, InstanceState.STARTING, "", "")
            booted = self._adb.wait_booted(instance.config.adb_port, timeout=BOOT_TIMEOUT_S)
            if booted:
                try:
                    self._apply_post_boot(instance, image)
                except Exception as exc:
                    log.run("log_post_boot_failed", level="WARNING",
                            id=instance.name, detail=str(exc)[:200])
                instance.state = InstanceState.RUNNING
                instance.last_error = ""
                instance.last_error_detail = ""
                log.run("log_instance_running", id=instance.name)
                self._notify(instance.id, InstanceState.RUNNING, "", "")
            else:
                log.run("log_boot_timeout", level="WARNING", id=instance.name)
                instance.state = InstanceState.STARTING
                self._notify(instance.id, InstanceState.STARTING, "", "")
        except Exception as exc:  # noqa: BLE001 兜底保护
            self._fail(instance, "err_unknown", str(exc)[:300])
        finally:
            done.set()

    def _fail(self, instance: Instance, key: str, detail: str) -> None:
        instance.state = InstanceState.ERROR
        instance.last_error = key
        instance.last_error_detail = detail
        get_logger().error(key, id=instance.name, detail=(detail or "")[:300])
        self._notify(instance.id, InstanceState.ERROR, key, detail)

    def _persist_config(self, instance: Instance) -> None:
        if self.save_instance_config:
            try:
                self.save_instance_config(instance)
            except Exception:
                pass

    # ------------------------------------------------------------- ports
    def _ensure_ports(self, instance: Instance, force: bool = False) -> bool:
        from adb import port_allocator
        from core.instance_manager import used_ports_of
        used_adb, used_display, used_agent = used_ports_of(self._all_instances())
        ok = True
        if force or not instance.config.adb_port:
            port = port_allocator.find_free_port(5555, 6000, used_adb)
            if port is None:
                ok = False
            else:
                instance.config.adb_port = port
        if force or instance.config.vnc_display < 0:
            display = port_allocator.find_free_display(used_display)
            if display is None:
                ok = False
            else:
                instance.config.vnc_display = display
        if force or not instance.config.agent_port:
            agent = port_allocator.find_free_port(20000, 60000, used_agent)
            if agent is None:
                ok = False
            else:
                instance.config.agent_port = agent
        if ok:
            self._persist_config(instance)
        return ok

    def _all_instances(self) -> List[Instance]:
        if getattr(self, "list_instances", None):
            return self.list_instances()
        return []

    # ------------------------------------------------------------- overlay
    def _ensure_overlay(self, overlay: Path, image: AndroidImage) -> None:
        if overlay.exists():
            return
        base = image.base_drive()
        if base is None:
            raise RuntimeError("image has no base drive")
        backing = image.file_path(base["file"])
        qemu_img = self.locate_qemu_img()
        if qemu_img is None:
            raise RuntimeError("qemu-img not found")
        fmt = base.get("format", "raw")
        subprocess.run(
            [qemu_img, "create", "-f", "qcow2",
             "-o", f"backing_file={backing}", f"backing_fmt={fmt}", str(overlay)],
            capture_output=True, text=True, timeout=120, check=True,
            creationflags=CREATE_NO_WINDOW,
        )

    def _ensure_data_disk(self, path: Path, size_gb: int = 32) -> None:
        """创建实例 /data 数据盘（空 qcow2，fstab.stararm 挂载时 formattable 格式化）。"""
        if path.exists():
            return
        qemu_img = self.locate_qemu_img()
        if qemu_img is None:
            raise RuntimeError("qemu-img not found")
        subprocess.run(
            [qemu_img, "create", "-f", "qcow2", str(path), f"{int(size_gb)}G"],
            capture_output=True, text=True, timeout=120, check=True,
            creationflags=CREATE_NO_WINDOW,
        )

    # ------------------------------------------------------------- spawn
    @staticmethod
    def _spawn(qemu_bin: str, args: List[str]):
        proc = subprocess.Popen(
            [qemu_bin] + args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
        out_buf: Deque[str] = deque()
        err_buf: Deque[str] = deque()
        _PipeReader(proc.stdout, out_buf).start()
        _PipeReader(proc.stderr, err_buf).start()
        return proc, err_buf, out_buf

    @staticmethod
    def _wait_early_exit(proc: subprocess.Popen, window_s: float) -> Optional[int]:
        """window 秒内退出返回退出码，存活返回 None。"""
        deadline = time.time() + window_s
        while time.time() < deadline:
            rc = proc.poll()
            if rc is not None:
                time.sleep(0.3)
                return rc
            time.sleep(0.25)
        return None

    # ------------------------------------------------------------- post boot
    def _apply_post_boot(self, instance: Instance, image: AndroidImage) -> None:
        port = instance.config.adb_port
        agent = GuestAgentClient(port=instance.config.agent_port)
        self._adb.adb_root(port)
        apply_profile(self._adb, agent, instance.config, image.android_version)
        try:
            w, h = _parse_resolution(instance.config.resolution)
            if w and h:
                self._adb.wm_size(port, w, h)
            self._adb.wm_density(port, instance.config.dpi)
        except Exception as exc:
            get_logger().run("log_display_apply_failed", level="WARNING", detail=str(exc)[:200])

    # ------------------------------------------------------------- stop
    def stop(self, instance: Instance, force: bool = False, wait: bool = False) -> None:
        done = threading.Event()
        t = threading.Thread(target=self._stop_flow, args=(instance, force, done), daemon=True)
        t.start()
        if wait:
            done.wait(90)

    def _stop_flow(self, instance: Instance, force: bool, done: threading.Event) -> None:
        log = get_logger()
        instance.state = InstanceState.STOPPING
        self._notify(instance.id, InstanceState.STOPPING, "", "")
        with self._lock:
            rt = self._runtime.get(instance.id)
            self._stopping.add(instance.id)
        proc = rt.get("proc") if rt else None
        pid = (rt or {}).get("pid") or self._read_pid(instance.id)
        try:
            if force:
                self._kill(proc, pid)
            else:
                # 优雅关机：先系统内关机，失败再强制
                if instance.config.adb_port:
                    try:
                        self._adb.poweroff(instance.config.adb_port)
                    except Exception:
                        pass
                if not self._wait_exit(proc, pid, 45):
                    self._terminate(proc, pid)
                    if not self._wait_exit(proc, pid, 10):
                        self._kill(proc, pid)
        finally:
            with self._lock:
                self._runtime.pop(instance.id, None)
                self._stopping.discard(instance.id)
            try:
                self._pid_file(instance.id).unlink(missing_ok=True)
            except OSError:
                pass
            instance.state = InstanceState.STOPPED
            log.run("log_instance_stopped", id=instance.name)
            self._notify(instance.id, InstanceState.STOPPED, "", "")
            done.set()

    @staticmethod
    def _wait_exit(proc, pid: Optional[int], timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc is not None:
                if proc.poll() is not None:
                    return True
            elif pid is not None and not _pid_alive(pid):
                return True
            time.sleep(0.5)
        if proc is not None:
            return proc.poll() is not None
        return not (pid and _pid_alive(pid))

    @staticmethod
    def _terminate(proc, pid: Optional[int]) -> None:
        if proc is not None:
            try:
                proc.terminate()
                return
            except Exception:
                pass
        if pid:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW,
            )

    @staticmethod
    def _kill(proc, pid: Optional[int]) -> None:
        if proc is not None:
            try:
                proc.kill()
                return
            except Exception:
                pass
        if pid:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW,
            )

    # ------------------------------------------------------------- args
    @staticmethod
    def build_args(
        instance: Instance,
        image: AndroidImage,
        accel: str = "whpx",
        graphics: str = "virgl",
        overlay: Optional[Path] = None,
        data_disk: Optional[Path] = None,
    ) -> List[str]:
        """构建 QEMU 命令行（纯函数，可单元测试）。

        overlay = 实例根盘 CoW qcow2（backing=镜像基盘，backing_fmt=raw），
        data_disk = /data 实例数据盘（qcow2，fstab.stararm → /dev/nvme1n1）。
        """
        cfg: InstanceConfig = instance.config
        args: List[str] = [
            "-M", "virt",
            "-cpu", "cortex-a76",
            "-smp", str(int(cfg.cpu_cores)),
            "-m", f"{int(cfg.memory_mb)}M",
            "-accel", accel if accel != "tcg" else "tcg,thread=multi",
            "-name", f"stararm-{instance.id[:8]}",
        ]
        # 内核 / ramdisk / dtb / 启动参数（androidboot.serialno 注入自定义序列号）
        args += ["-kernel", _host_without_drive(image.file_path(image.manifest.kernel))]
        if image.manifest.ramdisk:
            args += ["-initrd", _host_without_drive(image.file_path(image.manifest.ramdisk))]
        if image.manifest.dtb:
            args += ["-dtb", _host_without_drive(image.file_path(image.manifest.dtb))]
        cmdline = image.manifest.cmdline
        if cfg.device.serial:
            cmdline = f"{cmdline} androidboot.serialno={cfg.device.serial}"
        args += ["-append", cmdline]

        # 磁盘（ikconfig 无 virtio-blk → NVMe）：
        #  root = 实例 CoW overlay（rw）。CI 实证只读基盘会在 ext4 挂载写超级块时
        #  被 QEMU 拒写（EPERM→挂根失败），故基盘本身不挂载（保持跨实例只读隔离），
        #  写入全部落在 overlay；/data = 第二块独立 qcow2（fstab → /dev/nvme1n1）
        index = 0
        for drive in image.manifest.drives:
            is_base = str(drive.get("base", "")).lower() in ("1", "true", "yes")
            if is_base:
                if overlay is None:
                    raise ValueError("base drive requires overlay (root disk must be CoW)")
                disk_file, disk_fmt = _host_without_drive(overlay), "qcow2"
            else:
                disk_file = _host_without_drive(image.file_path(drive["file"]))
                disk_fmt = drive.get("format", "raw")
            args += [
                "-drive", f"if=none,file={disk_file},format={disk_fmt},id=hd{index}",
                "-device", f"nvme,drive=hd{index},serial=stararm{index}",
            ]
            index += 1
        if data_disk is not None:
            args += [
                "-drive", f"if=none,file={_host_without_drive(data_disk)},format=qcow2,id=hd{index}",
                "-device", f"nvme,drive=hd{index},serial=stararm{index}",
            ]

        # 图形加速：VirGL（OpenGL ES / Vulkan via Venus），VNC 显示转发
        if graphics == "virgl-vulkan":
            args += ["-device", "virtio-gpu-gl-device,venus=on", "-display", "egl-headless"]
        elif graphics == "virgl":
            args += ["-device", "virtio-gpu-gl-device", "-display", "egl-headless"]
        else:
            args += ["-device", "virtio-gpu-device", "-display", "none"]
        if cfg.vnc_display >= 0:
            args += ["-vnc", f"127.0.0.1:{int(cfg.vnc_display)}"]

        # 网络：内核无 virtio-net（# CONFIG_VIRTIO_NET is not set），ADB 管理通道
        # 走用户网络 hostfwd；guest 侧网卡为 QEMU usb-net（CDC ECM + RNDIS 双协议，
        # 内核 CONFIG_USB_XHCI_HCD=y，cdc_ether/usbnet 模块在 system_dlkm）
        adb_hostfwd = f"tcp:127.0.0.1:{int(cfg.adb_port)}-:5555"
        if cfg.network_mode == "bridge":
            args += [
                "-device", "qemu-xhci,id=xhci",
                "-netdev", f"tap,id=net0,ifname={cfg.bridge_adapter or 'tap0'}",
                "-device", "usb-net,netdev=net0",
                "-netdev", f"user,id=netmgmt,hostfwd={adb_hostfwd}",
                "-device", "usb-net,netdev=netmgmt",
            ]
        else:
            args += [
                "-device", "qemu-xhci,id=xhci",
                "-netdev", f"user,id=net0,hostfwd={adb_hostfwd}",
                "-device", "usb-net,netdev=net0",
            ]

        # 客户代理通道（virtio-serial）：GPS / 剪贴板 / IMEI / 属性
        if cfg.agent_port:
            args += [
                "-chardev", f"socket,id=ga0,host=127.0.0.1,port={int(cfg.agent_port)},server=on,wait=off",
                "-device", "virtio-serial-device",
                "-device", "virtserialport,chardev=ga0,name=stararm.agent",
            ]

        # 随机数：ikconfig `# CONFIG_HW_RANDOM_VIRTIO is not set`，virtio-rng 无后端驱动，不挂
        return args


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return False
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _parse_resolution(resolution: str) -> Tuple[int, int]:
    try:
        w, h = str(resolution).lower().split("x", 1)
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 0, 0
