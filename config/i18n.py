"""语言包加载与翻译：简体中文 / 英文双语，预留多语言扩展接口。

默认跟随系统语言；支持运行期切换，实时生效，无需重启。
本模块不依赖 GUI，GUI/CLI/日志共用。
"""
import json
import locale
import threading
from typing import Callable, Dict, List, Optional

from config import paths

SUPPORTED_LANGUAGES = ("zh_CN", "en_US")
DEFAULT_LANGUAGE = "en_US"


def system_language() -> str:
    """跟随系统语言：中文系统 -> 简体中文，其他 -> 英文。"""
    try:
        code = (locale.getdefaultlocale()[0] or "")
    except Exception:
        code = ""
    if code.lower().startswith("zh"):
        return "zh_CN"
    return DEFAULT_LANGUAGE


class Translator:
    """翻译器：加载 JSON 语言包，带参数插值与切换回调。"""

    def __init__(self, lang: str = "system", i18n_dir=None) -> None:
        self._lock = threading.RLock()
        self._lang = lang
        self._resolved = self._resolve(lang)
        self._packs: Dict[str, Dict[str, str]] = {}
        self._listeners: List[Callable[[str], None]] = []
        self._i18n_dir = i18n_dir

    @staticmethod
    def _resolve(lang: str) -> str:
        if lang in SUPPORTED_LANGUAGES:
            return lang
        return system_language()

    @property
    def language(self) -> str:
        return self._lang

    @property
    def resolved_language(self) -> str:
        return self._resolved

    def _dir(self):
        if self._i18n_dir is not None:
            return self._i18n_dir
        return paths.resource_dir() / "i18n"

    def _load_pack(self, code: str) -> Dict[str, str]:
        if code not in self._packs:
            try:
                data = json.loads((self._dir() / f"{code}.json").read_text(encoding="utf-8"))
                self._packs[code] = data
            except (OSError, ValueError):
                self._packs[code] = {}
        return self._packs[code]

    def set_language(self, lang: str) -> None:
        """切换语言，实时生效：'system' | 'zh_CN' | 'en_US'。"""
        if lang not in ("system",) + SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language: {lang}")
        with self._lock:
            self._lang = lang
            self._resolved = self._resolve(lang)
            resolved = self._resolved
        for cb in list(self._listeners):
            try:
                cb(resolved)
            except Exception:
                pass

    def available(self) -> List[str]:
        return list(SUPPORTED_LANGUAGES)

    def add_change_listener(self, callback: Callable[[str], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def tr(self, key: str, **params) -> str:
        """取词条；缺失时回退英文包，再缺失返回 key 本身。"""
        with self._lock:
            pack = self._load_pack(self._resolved)
        text = pack.get(key)
        if text is None:
            fallback = self._load_pack(DEFAULT_LANGUAGE)
            text = fallback.get(key)
        if text is None:
            return key
        if params:
            try:
                return text.format(**params)
            except (KeyError, IndexError, ValueError):
                return text
        return text


_translator: Optional[Translator] = None


def get_translator() -> Translator:
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def tr(key: str, **params) -> str:
    return get_translator().tr(key, **params)
