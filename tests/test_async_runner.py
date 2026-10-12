"""异步错误提示：带 i18n 词条 key 的异常输出本地化文案（不弹堆栈），未知异常保留技术细节。"""
import pytest

pytest.importorskip("PySide6")

from config.i18n import tr
from gui.widgets.async_runner import format_error
from mirror.image_manager import ImageManagerError


def test_keyed_error_translated_without_traceback():
    text = format_error("boom\nTraceback (most recent call last): ...",
                        ImageManagerError("err_no_image_source", ""))
    assert text == tr("err_no_image_source")
    assert "Traceback" not in text


def test_keyed_error_keeps_technical_detail():
    text = format_error("raw",
                        ImageManagerError("err_image_download_failed", "<urlopen error 404>"))
    assert tr("err_image_download_failed") in text
    assert "<urlopen error 404>" in text


def test_unknown_error_falls_back_with_detail():
    text = format_error("raw detail", ValueError("x"))
    assert tr("err_unknown") in text
    assert "raw detail" in text
