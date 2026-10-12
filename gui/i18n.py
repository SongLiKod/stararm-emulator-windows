"""GUI 翻译注册表：所有界面文本 bind 到词条；切换语言实时重刷（无需重启软件）。"""
import weakref
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal
from config.i18n import get_translator, tr as base_tr


def tr(key: str, **params) -> str:
    return base_tr(key, **params)


class Retranslator(QObject):
    """控件 <-> 词条绑定注册表；语言切换后全部实时重刷。"""

    language_changed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._bindings = []  # (weakref, key, attr, params)
        get_translator().add_change_listener(self._on_language)

    def bind(self, widget: Any, key: str, attr: str = "text",
             params: Optional[dict] = None) -> None:
        self._bindings.append((weakref.ref(widget), key, attr, params))
        self._apply(widget, key, attr, params)

    def rebind(self, widget: Any, key: str, attr: str = "text",
               params: Optional[dict] = None) -> None:
        """更新已绑定控件的词条（同一控件按状态切换文案），语言切换仍实时生效。"""
        ref = weakref.ref(widget)
        for index, (old_ref, _key, old_attr, _params) in enumerate(self._bindings):
            if old_attr == attr and old_ref() is widget:
                self._bindings[index] = (ref, key, attr, params)
                break
        else:
            self._bindings.append((ref, key, attr, params))
        self._apply(widget, key, attr, params)

    def _apply(self, widget: Any, key: str, attr: str, params: Optional[dict]) -> None:
        text = base_tr(key, **(params or {}))
        try:
            setter = getattr(widget, f"set{attr[0].upper()}{attr[1:]}")
            setter(text)
        except AttributeError:
            try:
                setattr(widget, attr, text)
            except Exception:
                pass
        except Exception:
            pass

    def _on_language(self, lang: str) -> None:
        stale = []
        for ref, key, attr, params in self._bindings:
            widget = ref()
            if widget is None:
                stale.append((ref, key, attr, params))
                continue
            try:
                self._apply(widget, key, attr, params)
            except RuntimeError:
                stale.append((ref, key, attr, params))
        for item in stale:
            try:
                self._bindings.remove(item)
            except ValueError:
                pass
        self.language_changed.emit(lang)

    def retranslate(self) -> None:
        self._on_language(get_translator().resolved_language)


RETRANSLATOR = Retranslator()


def bind(widget: Any, key: str, attr: str = "text", params: Optional[dict] = None) -> None:
    RETRANSLATOR.bind(widget, key, attr, params)


def rebind(widget: Any, key: str, attr: str = "text", params: Optional[dict] = None) -> None:
    RETRANSLATOR.rebind(widget, key, attr, params)
