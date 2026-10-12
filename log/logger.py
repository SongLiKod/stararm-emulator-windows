"""星模日志器：系统日志 / 运行日志 / 错误日志。

- 三类日志文件存放于用户数据目录 logs/：system.log、run.log、error.log
- 支持自动轮转（单文件约 1MB，各保留 3 份）
- 日志内容为双语词条（i18n key + 参数），界面按当前语言实时渲染，文件落盘为“词条 + 双语译文”
- 无任何网络上传、无广告、无后台驻留冗余进程
"""
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from config import paths
from config.i18n import get_translator

MAX_LOG_BYTES = 1024 * 1024
ROTATE_KEEP = 3


class LogLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogCategory:
    SYSTEM = "system"
    RUN = "run"
    ERROR = "error"


@dataclass
class LogEntry:
    timestamp: float
    level: LogLevel
    category: str
    key: str
    params: Dict[str, object] = field(default_factory=dict)

    def time_text(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))

    def text(self) -> str:
        """按当前语言渲染日志文本。"""
        return get_translator().tr(self.key, **self.params)


class StarARMLogger:
    """进程内单例日志器。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: List[Callable[[LogEntry], None]] = []
        self._files: Dict[str, Optional[object]] = {}
        self._trans = get_translator()

    # ------------------------------------------------------------------ file
    def _file_path(self, category: str):
        return paths.logs_dir() / f"{category}.log"

    def _rotate_if_needed(self, category: str) -> None:
        f = self._file_path(category)
        try:
            if f.stat().st_size < MAX_LOG_BYTES:
                return
        except OSError:
            return
        for i in range(ROTATE_KEEP - 1, 0, -1):
            src = f.with_suffix(f".log.{i}")
            dst = f.with_suffix(f".log.{i + 1}")
            if src.exists():
                try:
                    src.replace(dst)
                except OSError:
                    pass
        try:
            f.replace(f.with_suffix(".log.1"))
        except OSError:
            pass

    def _write(self, entry: LogEntry) -> None:
        self._rotate_if_needed(entry.category)
        zh = self._trans.tr(entry.key, **entry.params) if self._trans.resolved_language != "zh_CN" else ""
        en = self._trans.tr(entry.key, **entry.params)
        lines = [
            f"{entry.time_text()} [{entry.level.value}] [{entry.category}] {entry.key}"
        ]
        if zh and zh != entry.key:
            lines.append(f"    ZH: {zh}")
        if en != entry.key:
            lines.append(f"    EN: {en}")
        try:
            with self._file_path(entry.category).open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ log
    def log(self, category: str, key: str, level: LogLevel = LogLevel.INFO, **params) -> LogEntry:
        entry = LogEntry(time.time(), level, category, key, params)
        with self._lock:
            self._write(entry)
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(entry)
            except Exception:
                pass
        return entry

    def system(self, key: str, level: LogLevel = LogLevel.INFO, **params) -> LogEntry:
        return self.log(LogCategory.SYSTEM, key, level, **params)

    def run(self, key: str, level: LogLevel = LogLevel.INFO, **params) -> LogEntry:
        return self.log(LogCategory.RUN, key, level, **params)

    def error(self, key: str, level: LogLevel = LogLevel.ERROR, **params) -> LogEntry:
        return self.log(LogCategory.ERROR, key, level, **params)

    def add_listener(self, callback: Callable[[LogEntry], None]) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def recent(self, category: str, limit: int = 200) -> List[LogEntry]:
        """从日志文件尾部读取最近条目（供 GUI 打开时回填）。"""
        entries: List[LogEntry] = []
        f = self._file_path(category)
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return entries
        for line in text.splitlines()[-(limit * 2):]:
            line = line.strip()
            if not line or line.startswith("    "):
                continue
            # 格式：时间 [级别] [分类] key
            try:
                ts = time.mktime(time.strptime(line[0:19], "%Y-%m-%d %H:%M:%S"))
                rest = line[20:]
                level = LogLevel(rest.split("]")[0].lstrip("["))
                category_ = rest.split("]")[1].lstrip("[")
                key = rest.split("] ", 1)[1]
                entries.append(LogEntry(ts, level, category_, key, {}))
            except Exception:
                continue
        return entries[-limit:]


_logger: Optional[StarARMLogger] = None
_logger_lock = threading.Lock()


def get_logger() -> StarARMLogger:
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = StarARMLogger()
    return _logger
