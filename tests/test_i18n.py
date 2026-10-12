"""i18n 测试：双语完整性（含源码词条扫描）、插值、跟随系统。"""
import json
import re
from pathlib import Path

import pytest

from config.i18n import SUPPORTED_LANGUAGES, Translator, system_language
from config import paths

REPO = Path(__file__).resolve().parents[1]

# 源码中直接以字符串常量引用的词条（列头 / 标签页 / 横幅 / 动态 key 家族）
EXPLICIT_KEYS = [
    "col_name", "col_status", "col_cpu", "col_memory", "col_disk",
    "col_android", "col_adb", "col_actions",
    "tab_log_system", "tab_log_run", "tab_log_error",
    "vt_banner_text", "btn_open_guide",
    "state_stopped", "state_starting", "state_running",
    "state_stopping", "state_error", "state_unknown",
    "theme_system", "theme_light", "theme_dark",
    "lang_system", "lang_zh", "lang_en",
    "step_tap", "step_swipe", "step_key", "step_text", "step_sleep",
    "action_tap", "action_swipe", "action_key", "action_text",
    "err_start_failed",
]

# 扫描模式：精确匹配 i18n 使用点
SCAN_PATTERNS = [
    r"\btr\(\s*[\"']([a-z0-9_]+)[\"']",
    r"\bT\.tr\(\s*[\"']([a-z0-9_]+)[\"']",
    r"\bbind\(\s*[\w.]+,\s*[\"']([a-z0-9_]+)[\"']",
    r"\bp\(\s*[\"']([a-z0-9_]+)[\"']",
    r"\bfail\(\s*[\"']([a-z0-9_]+)[\"']",
    r"\.system\(\s*[\"']([a-z0-9_]+)[\"']",
    r"\.run\(\s*[\"']([a-z0-9_]+)[\"']",
    r"\.error\(\s*[\"']([a-z0-9_]+)[\"']",
    r"(?:AdbError|ImageManagerError|RuntimeError|KeyError)\(\s*[\"']([a-z0-9_]+)[\"']",
    r"ERROR_\w+\s*=\s*[\"']([a-z0-9_]+)[\"']",
    r"_(?:ok|fail)_key\s*=\s*[\"']([a-z0-9_]+)[\"']",
]


def load_pack(code: str) -> dict:
    path = REPO / "resource" / "i18n" / f"{code}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def collect_source_keys() -> set:
    keys = set(EXPLICIT_KEYS)
    src_files = [
        p for p in (REPO).rglob("*.py")
        if "tests" not in p.parts and ".github" not in p.parts
        and "build" not in p.parts
    ]
    for f in src_files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for pattern in SCAN_PATTERNS:
            for match in re.findall(pattern, text):
                if match.startswith(("err_", "msg_", "log_", "cli_", "btn_",
                                     "dlg_", "lbl_", "tab_", "col_", "state_",
                                     "vt_", "vnc_", "grp_", "cell_", "net_",
                                     "action_", "step_", "theme_", "lang_",
                                     "hint_", "status_", "about_", "app_",
                                     "menu_", "act_", "zoom_")) or "_" in match:
                    keys.add(match)
    return keys


def test_packs_have_identical_keys():
    zh = load_pack("zh_CN")
    en = load_pack("en_US")
    assert set(zh.keys()) == set(en.keys()), (
        f"key mismatch: zh_only={set(zh) - set(en)} en_only={set(en) - set(zh)}")


def test_all_source_keys_are_bilingual():
    """所有源码引用的词条在两种语言包中都存在（双语适配完整性）。"""
    zh = load_pack("zh_CN")
    en = load_pack("en_US")
    keys = collect_source_keys()
    missing_zh = keys - set(zh)
    missing_en = keys - set(en)
    assert not missing_zh, f"missing in zh_CN.json: {sorted(missing_zh)}"
    assert not missing_en, f"missing in en_US.json: {sorted(missing_en)}"


def test_supported_languages():
    assert "zh_CN" in SUPPORTED_LANGUAGES
    assert "en_US" in SUPPORTED_LANGUAGES


def test_interpolation_and_fallback():
    t = Translator()
    t.set_language("zh_CN")
    assert "{name}" not in t.tr("msg_confirm_delete", name="测试")
    assert "测试" in t.tr("msg_confirm_delete", name="测试")
    assert t.tr("definitely_missing_key_xyz") == "definitely_missing_key_xyz"


def test_system_language_follows_locale():
    assert system_language() in ("zh_CN", "en_US")


def test_switch_real_time():
    t = Translator()
    events = []
    t.add_change_listener(events.append)
    t.set_language("zh_CN")
    assert t.resolved_language == "zh_CN"
    t.set_language("en_US")
    assert t.resolved_language == "en_US"
    assert len(events) >= 2


def test_i18n_dir_exists():
    d = paths.resource_dir() / "i18n"
    for code in SUPPORTED_LANGUAGES:
        assert (d / f"{code}.json").is_file()
