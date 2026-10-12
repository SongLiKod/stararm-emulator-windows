"""资源超限保护测试：全局阈值、创建/启动校验。"""
from config.settings import SettingsManager
from core.resource_guard import ResourceGuard, host_cpu_cores, host_memory_gb


def make_guard(max_instances=4, max_cpu=0, max_mem=0) -> ResourceGuard:
    m = SettingsManager()
    m.update(max_instances=max_instances, max_total_cpu_cores=max_cpu,
             max_total_memory_gb=max_mem)
    return ResourceGuard(m)


def test_host_info_positive():
    assert host_cpu_cores() >= 1
    assert host_memory_gb() >= 1


def test_auto_thresholds():
    guard = make_guard()
    t = guard.thresholds()
    assert t.max_instances >= 1
    assert t.max_total_cpu_cores >= 1
    assert t.max_total_memory_gb >= 1
    assert t.max_total_cpu_cores <= host_cpu_cores()
    assert t.max_total_memory_gb <= host_memory_gb() + 0.01


def test_explicit_thresholds():
    guard = make_guard(max_instances=3, max_cpu=8, max_mem=16)
    t = guard.thresholds()
    assert t.max_instances == 3
    assert t.max_total_cpu_cores == 8
    assert t.max_total_memory_gb == 16


def test_check_create_blocks_at_limit():
    guard = make_guard(max_instances=2)
    ok, reason = guard.check_create(1)
    assert ok
    ok, reason = guard.check_create(2)
    assert not ok
    assert reason == "err_max_instances"


def test_check_start_blocks_over_cpu_threshold():
    guard = make_guard(max_instances=16, max_cpu=4, max_mem=64)
    ok, reason = guard.check_start(4, 4096, [])
    assert ok
    ok, reason = guard.check_start(8, 4096, [])
    assert not ok
    assert reason == "err_max_total_cpu"


def test_check_start_blocks_over_memory_threshold():
    guard = make_guard(max_instances=16, max_cpu=64, max_mem=8)
    ok, reason = guard.check_start(4, 4096, [])
    assert ok
    ok, reason = guard.check_start(4, 9216, [])
    assert not ok
    assert reason == "err_max_total_mem"


def test_check_start_counts_running_instances():
    guard = make_guard(max_instances=2, max_cpu=64, max_mem=64)
    ok, reason = guard.check_start(4, 4096, [(4, 4096)])
    assert ok
    ok, reason = guard.check_start(4, 4096, [(4, 4096), (4, 4096)])
    assert not ok
