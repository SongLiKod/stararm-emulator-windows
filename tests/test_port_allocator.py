"""端口分配测试：独立 ADB 端口、VNC display、客户代理端口，无端口冲突。"""
import socket

import pytest

from adb.port_allocator import allocate_ports, find_free_display, find_free_port


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def test_find_free_port_returns_bindable():
    port = find_free_port(20000, 25000)
    assert port is not None
    assert 20000 <= port <= 25000
    assert _is_free(port)


def test_find_free_port_respects_exclude():
    port = find_free_port(20000, 25000, exclude=set(range(20000, 24000)))
    assert port >= 24000


def test_find_free_port_none_when_all_excluded():
    assert find_free_port(20000, 20010, exclude=set(range(20000, 20011))) is None


def test_find_free_display():
    display = find_free_display()
    assert display is not None
    assert 0 <= display <= 200
    assert _is_free(5900 + display)


def test_find_free_display_respects_exclude():
    display = find_free_display(exclude=set(range(0, 100)))
    assert display >= 100


def test_allocate_ports_unique_and_usable():
    adb, display, agent = allocate_ports()
    assert adb != agent
    assert 5900 + display != adb and 5900 + display != agent
    assert _is_free(adb) and _is_free(agent) and _is_free(5900 + display)


def test_allocate_ports_avoids_conflicts():
    adb1, disp1, agent1 = allocate_ports()
    adb2, disp2, agent2 = allocate_ports(
        used_adb={adb1}, used_displays={disp1}, used_agent={agent1})
    assert adb2 != adb1 and disp2 != disp1 and agent2 != agent1


def test_allocate_ports_raises_when_exhausted():
    with pytest.raises(RuntimeError):
        allocate_ports(used_adb=set(range(5555, 6001)))
