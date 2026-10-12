"""异步任务执行器：后台线程执行 + 模态进度 + GUI 线程回调。"""
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from gui.i18n import tr


class _Worker(QObject):
    finished_ok = Signal(object)
    failed = Signal(str, object)

    def __init__(self, job: Callable[[], Any]) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:
        try:
            result = self._job()
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            detail = f"{exc}\n{traceback.format_exc(limit=3)}"
            self.failed.emit(detail[:800], exc)


def format_error(detail: str, exc: object = None) -> str:
    """把后台异常转成给用户看的提示：带 i18n 词条 key 的异常输出本地化文案（不带堆栈），
    未知异常保留 err_unknown + 技术细节。"""
    key = getattr(exc, "key", None)
    if isinstance(key, str) and key:
        text = tr(key)
        if text != key:
            extra = str(getattr(exc, "detail", "") or "").strip()
            return f"{text}\n{extra[:300]}" if extra else text
    return f"{tr('err_unknown')}\n{detail[:400]}"


class AsyncRunner(QObject):
    """模态进度 + 后台线程执行 + 完成/失败回调（GUI 线程）。"""

    def __init__(self, parent: Optional[QWidget], label: str,
                 job: Callable[[], Any],
                 on_done: Optional[Callable[[Any], None]] = None,
                 on_fail: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(parent)
        self._dialog: Optional[QProgressDialog] = None
        if parent is not None:
            self._dialog = QProgressDialog(label, "", 0, 0, parent)
            self._dialog.setCancelButton(None)
            self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self._dialog.setMinimumDuration(150)
            self._dialog.setAutoClose(False)
            self._dialog.setAutoReset(False)
        self._thread = QThread(self)
        self._worker = _Worker(job)
        self._worker.moveToThread(self._thread)
        self._on_done = on_done
        self._on_fail = on_fail or (lambda detail: AsyncRunner.show_error(parent, detail))
        self._thread.started.connect(self._worker.run)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.failed.connect(self._on_error)

    def start(self) -> None:
        self._thread.start()

    def _on_ok(self, result: Any) -> None:
        self._thread.quit()
        self._thread.wait(3000)
        if self._dialog is not None:
            self._dialog.close()
        if self._on_done is not None:
            self._on_done(result)

    def _on_error(self, detail: str, exc: object) -> None:
        self._thread.quit()
        self._thread.wait(3000)
        if self._dialog is not None:
            self._dialog.close()
        self._on_fail(format_error(detail, exc))

    @staticmethod
    def show_error(parent: Optional[QWidget], detail: str) -> None:
        QMessageBox.warning(parent, tr("msg_error"), detail[:400])
