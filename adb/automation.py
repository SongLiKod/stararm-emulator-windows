"""批量自动化调度：批量启停、批量安装、批量配置（供 GUI 与 CLI 共用）。"""
from typing import Callable, Iterable, List, Optional

from config.i18n import get_translator
from log.logger import get_logger


class BatchResult:
    def __init__(self) -> None:
        self.success: List[str] = []
        self.failed: List[str] = []

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self, done_key: str, fail_key: str) -> str:
        trans = get_translator()
        parts = [trans.tr(done_key, ok=len(self.success), fail=len(self.failed))]
        if self.failed:
            parts.append(trans.tr(fail_key, ids=", ".join(self.failed)))
        return " ".join(parts)


def batch_operation(
    ids: Iterable[str],
    action: Callable[[str], None],
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> BatchResult:
    """对多个实例执行同一操作，逐个执行、互不影响。"""
    result = BatchResult()
    ids = list(ids)
    total = len(ids)
    for index, iid in enumerate(ids):
        try:
            action(iid)
            result.success.append(iid)
        except Exception as exc:
            result.failed.append(iid)
            get_logger().error("log_batch_item_failed", id=iid, detail=str(exc)[:200])
        if progress:
            try:
                progress(iid, index + 1, total)
            except Exception:
                pass
    return result
