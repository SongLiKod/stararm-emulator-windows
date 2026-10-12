"""QEMU 调度测试：命令行构建（纯函数）与启动故障分类。"""
from pathlib import Path

from core.instance import Instance, InstanceConfig
from core.qemu_errors import classify_qemu_error, is_graphics_error
from core.qemu_manager import QemuManager
from mirror.image import ImageManifest


def make_image(tmp_path: Path):
    manifest = ImageManifest(
        id="aosp-13-arm64", name="AOSP 13", android_version=13,
        kernel="Image", ramdisk="ramdisk.img",
        cmdline="console=ttyAMA0 root=/dev/nvme0n1 rootwait rw",
        drives=[{"file": "system.img", "format": "raw", "id": "system",
                 "base": "true"}],
    )
    d = tmp_path / "aosp-13-arm64"
    d.mkdir()
    (d / "Image").write_bytes(b"kernel")
    (d / "ramdisk.img").write_bytes(b"ramdisk")
    (d / "system.img").write_bytes(b"system")
    from mirror.image import AndroidImage
    return AndroidImage(manifest, d, available=True)


def make_instance(tmp_path: Path, **overrides) -> Instance:
    cfg = InstanceConfig(cpu_cores=4, memory_mb=4096, disk_gb=32,
                         resolution="1280x720", dpi=320,
                         network_mode="nat", graphics="virgl-vulkan",
                         adb_port=5555, vnc_display=3, agent_port=25000)
    cfg.device.serial = "TESTSERIAL01"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return Instance(id="testid12345", name="t", image_id="aosp-13-arm64",
                    config=cfg)


def test_build_args_nat_whpx_virgl_vulkan(tmp_path):
    image = make_image(tmp_path)
    inst = make_instance(tmp_path)
    args = QemuManager.build_args(inst, image, accel="whpx",
                                  graphics="virgl-vulkan")
    text = " ".join(args)
    # ARM64 整机仿真
    assert "-M" in args and args[args.index("-M") + 1] == "virt"
    assert "-cpu" in args and args[args.index("-cpu") + 1] == "cortex-a76"
    # 独立资源
    assert args[args.index("-smp") + 1] == "4"
    assert args[args.index("-m") + 1] == "4096M"
    # 硬件虚拟化加速
    assert args[args.index("-accel") + 1] == "whpx"
    # 内核 + 启动参数 + 序列号注入
    assert "-kernel" in args and "-initrd" in args and "-append" in args
    assert "androidboot.serialno=" in text
    # 图形加速：VirGL + Vulkan(venus) + egl-headless + VNC
    assert "virtio-gpu-gl-device,venus=on" in args
    assert "egl-headless" in args
    assert args[args.index("-vnc") + 1] == "127.0.0.1:3"
    # NAT 网络 + 独立 ADB 端口 hostfwd（内核无 virtio-net → xhci + usb-net）
    assert f"tcp:127.0.0.1:5555-:5555" in text
    assert "-netdev" in args and "user,id=net0" in text
    assert "qemu-xhci" in text and "usb-net,netdev=net0" in text
    # 客户代理通道（virtio-serial）
    assert "host=127.0.0.1,port=25000,server=on,wait=off" in text
    assert "virtserialport" in text and "stararm.agent" in text


def test_build_args_virgl_only(tmp_path):
    image = make_image(tmp_path)
    inst = make_instance(tmp_path)
    args = QemuManager.build_args(inst, image, accel="whpx", graphics="virgl")
    assert "virtio-gpu-gl-device" in args
    assert not any("venus" in a for a in args)
    assert "egl-headless" in args


def test_build_args_software_graphics(tmp_path):
    image = make_image(tmp_path)
    inst = make_instance(tmp_path)
    args = QemuManager.build_args(inst, image, accel="tcg",
                                  graphics="software")
    assert "virtio-gpu-device" in args
    assert "egl-headless" not in args
    assert args[args.index("-accel") + 1] == "tcg,thread=multi"


def test_build_args_bridge_network_uses_tap_and_mgmt_net(tmp_path):
    image = make_image(tmp_path)
    inst = make_instance(tmp_path, network_mode="bridge",
                         bridge_adapter="tap-star")
    args = QemuManager.build_args(inst, image, accel="whpx",
                                  graphics="software")
    text = " ".join(args)
    assert "tap,id=net0,ifname=tap-star" in text
    # 桥接模式仍保留 ADB 管理通道（用户网络 hostfwd）
    assert f"tcp:127.0.0.1:5555-:5555" in text
    assert "user,id=netmgmt" in text


def test_build_args_overlay_drive(tmp_path):
    image = make_image(tmp_path)
    inst = make_instance(tmp_path)
    overlay = tmp_path / "overlay.qcow2"
    args = QemuManager.build_args(inst, image, accel="whpx",
                                  graphics="software", overlay=overlay)
    text = " ".join(args)
    assert str(overlay) in text and "format=qcow2" in text
    # 只读系统盘 + 实例覆盖盘（内核无 virtio-blk → NVMe 双盘）
    assert "readonly=on" in text
    assert "nvme,drive=hd0" in text and "nvme,drive=hd1" in text


def test_classify_qemu_error():
    assert classify_qemu_error("WHPX: Failed to initialize WHPX") == "err_virtualization"
    assert classify_qemu_error("failed to create EGL display") == "err_graphics"
    assert classify_qemu_error("virgl not supported") == "err_graphics"
    assert classify_qemu_error("Address already in use") == "err_port"
    assert classify_qemu_error("could not configure tap device") == "err_bridge"
    assert classify_qemu_error("No space left on device qcow2") == "err_disk"
    assert classify_qemu_error("could not open kernel Image") == "err_image"
    assert classify_qemu_error("totally unexpected") == "err_unknown"


def test_is_graphics_error():
    assert is_graphics_error("err_graphics")
    assert is_graphics_error("", "egl initialization failed")
    assert not is_graphics_error("err_port", "port in use")
