"""主题配色测试：严格按产品视觉规范（PRD 精确十六进制值）。"""
from config.theme import COMMON_COLORS, build_qss, load_all_themes, load_theme


def test_common_brand_colors_exact():
    # 主题通用主色（品牌核心色）
    assert COMMON_COLORS["primary"] == "#1677FF"
    assert COMMON_COLORS["success"] == "#36CFC9"
    assert COMMON_COLORS["warning"] == "#FF7D00"


def test_light_theme_exact():
    p = load_theme("light")
    assert p["background"] == "#F5F7FA"
    assert p["surface"] == "#FFFFFF"
    assert p["text"] == "#1D2129"
    assert p["text_secondary"] == "#86909C"
    assert p["border"] == "#E5E6EB"
    assert p["hover"] == "#E8F3FF"


def test_dark_theme_exact():
    p = load_theme("dark")
    assert p["background"] == "#121212"
    assert p["surface"] == "#1E1E2F"
    assert p["text"] == "#F2F3F5"
    assert p["text_secondary"] == "#86909C"
    assert p["border"] == "#2E2E42"
    assert p["hover"] == "#1F293D"


def test_brand_colors_merged_into_themes():
    themes = load_all_themes()
    for mode in ("light", "dark"):
        assert themes[mode]["primary"] == "#1677FF"
        assert themes[mode]["success"] == "#36CFC9"
        assert themes[mode]["warning"] == "#FF7D00"


def test_qss_contains_colors():
    qss = build_qss(load_theme("dark"))
    for color in ("#121212", "#1E1E2F", "#F2F3F5", "#2E2E42", "#1F293D",
                  "#1677FF", "#36CFC9", "#FF7D00"):
        assert color in qss
    assert "QPushButton#primary" in qss
    assert "QPushButton#danger" in qss


def test_modern_visual_tokens_present():
    for mode in ("light", "dark"):
        p = load_theme(mode)
        assert p["primary_hover"].startswith("#")
        assert p["primary_pressed"].startswith("#")
        assert p["success_text"].startswith("#")
        assert p["warning_text"].startswith("#")
        qss = build_qss(p)
        # 圆角卡片 / 现代化交互
        assert "border-radius: 12px" in qss
        assert "QPushButton#primary:hover" in qss
        assert "QHeaderView::section" in qss


def test_build_qss_tolerates_partial_palette():
    qss = build_qss({"background": "#101010"})
    assert "#101010" in qss
    assert "#FFFFFF" in qss  # 缺失配色走默认兜底，不会抛 KeyError
