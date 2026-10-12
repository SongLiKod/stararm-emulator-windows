"""主窗口：实例列表与状态展示、批量操作、拖拽 APK 安装、日志面板、
虚拟化状态检查（未开启时中文教程引导）、启动故障中文提示。"""
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from core.instance import Instance, InstanceState
from gui.dialogs import (
    CreateInstanceDialog, GlobalSettingsDialog, InstanceSettingsDialog,
    KeymapEditorDialog, MacroEditorDialog, VirtualizationGuideDialog,
)
from gui.display_window import DisplayWindow
from gui.i18n import RETRANSLATOR, bind, tr
from gui.theme import ThemeManager
from gui.widgets import LogPanel, StatusBadge, WarningBanner, AsyncRunner
from gui.widgets.status_badge import SUCCESS_COLOR, WARNING_COLOR
from tools import file_sync as sync_tool

COLS = ["col_name", "col_status", "col_cpu", "col_memory", "col_disk",
        "col_android", "col_adb", "col_actions"]


class QemuEventBridge(QObject):
    """QEMU 事件桥：后台线程 -> GUI 线程（队列信号）。"""

    instance_event = Signal(str, str, str, str)

    def emit_event(self, instance_id: str, state: str, error_key: str, detail: str) -> None:
        self.instance_event.emit(instance_id, state, error_key, detail)


class InstallPickerDialog(QDialog):
    """拖拽 APK 后选择安装目标实例。"""

    def __init__(self, parent, names: List[str], apk_count: int) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("dlg_pick_instances"))
        layout = QVBoxLayout(self)
        label = QLabel(tr("msg_drop_apk", count=apk_count))
        layout.addWidget(label)
        self._boxes: List[QCheckBox] = []
        for name in names:
            box = QCheckBox(name)
            box.setChecked(True)
            self._boxes.append(box)
            layout.addWidget(box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn_install"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def checked(self) -> List[str]:
        return [b.text() for b in self._boxes if b.isChecked()]


class MainWindow(QMainWindow):
    def __init__(self, service, theme: ThemeManager) -> None:
        super().__init__()
        self._service = service
        self._theme = theme
        self._displays: Dict[str, DisplayWindow] = {}
        self._recorders: Dict[str, ScreenRecorder] = {}
        self._rows: Dict[str, dict] = {}
        self._row_ids: List[str] = []
        self._pending_display: set = set()
        self._banner_shown = False

        self.setWindowTitle(f"{tr('app_title')} v{service.version}")
        self.setAcceptDrops(True)
        self.resize(1180, 760)

        self._bridge = QemuEventBridge(self)
        self._bridge.instance_event.connect(self._on_instance_event)
        service.qemu.add_listener(self._bridge.emit_event)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._banner = WarningBanner("vt_banner_text", "btn_open_guide")
        self._banner.action_requested.connect(self._open_vt_guide)
        self._banner.hide()
        root.addWidget(self._banner)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._table = QTableWidget(0, len(COLS))
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._log_panel = LogPanel()
        splitter.addWidget(self._table)
        splitter.addWidget(self._log_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 220])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self._build_menu()
        self._build_toolbar()
        self._build_status()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._tick)
        self._refresh_timer.start()

        self._theme_timer = QTimer(self)
        self._theme_timer.setInterval(2000)
        self._theme_timer.timeout.connect(self._poll_theme)
        self._theme_timer.start()

        RETRANSLATOR.language_changed.connect(lambda _lang: self._on_language_changed())
        self._theme.theme_changed.connect(lambda _t: None)

        self._set_table_headers()
        self._startup_check()

    # ================================================================ menu
    def _build_menu(self) -> None:
        menubar = self.menuBar()
        from PySide6.QtGui import QKeySequence

        self._menus = {}
        file_menu = menubar.addMenu(tr("menu_file"))
        self._menus["menu_file"] = file_menu
        self._act_new = QAction(tr("act_new_instance"), self)
        self._act_new.setShortcut(QKeySequence("Ctrl+N"))
        self._act_new.triggered.connect(self._create_instance)
        file_menu.addAction(self._act_new)

        self._act_import_image = QAction(tr("act_import_image"), self)
        self._act_import_image.triggered.connect(self._import_image)
        file_menu.addAction(self._act_import_image)
        self._act_export_instance = QAction(tr("act_export_instance"), self)
        self._act_export_instance.triggered.connect(self._export_instance)
        file_menu.addAction(self._act_export_instance)
        self._act_import_instance = QAction(tr("act_import_instance"), self)
        self._act_import_instance.triggered.connect(self._import_instance)
        file_menu.addAction(self._act_import_instance)
        file_menu.addSeparator()
        self._act_exit = QAction(tr("act_exit"), self)
        self._act_exit.triggered.connect(self.close)
        file_menu.addAction(self._act_exit)

        settings_menu = menubar.addMenu(tr("menu_settings"))
        self._menus["menu_settings"] = settings_menu
        self._act_global = QAction(tr("act_global_settings"), self)
        self._act_global.triggered.connect(self._open_global_settings)
        settings_menu.addAction(self._act_global)
        self._act_instance = QAction(tr("act_instance_settings"), self)
        self._act_instance.triggered.connect(self._open_selected_settings)
        settings_menu.addAction(self._act_instance)
        self._act_guide = QAction(tr("act_vt_guide"), self)
        self._act_guide.triggered.connect(self._open_vt_guide)
        settings_menu.addAction(self._act_guide)

        view_menu = menubar.addMenu(tr("menu_view"))
        self._menus["menu_view"] = view_menu
        theme_menu = view_menu.addMenu(tr("menu_theme"))
        self._menus["menu_theme"] = theme_menu
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions = {}
        for mode, key in (("system", "theme_system"), ("light", "theme_light"),
                          ("dark", "theme_dark")):
            act = QAction(tr(key), self)
            act.setCheckable(True)
            self._theme_group.addAction(act)
            theme_menu.addAction(act)
            self._theme_actions[mode] = act
            act.triggered.connect(lambda checked, m=mode: self._set_theme(m))
        lang_menu = view_menu.addMenu(tr("menu_language"))
        self._menus["menu_language"] = lang_menu
        self._lang_group = QActionGroup(self)
        self._lang_group.setExclusive(True)
        self._lang_actions = {}
        for code, key in (("system", "lang_system"), ("zh_CN", "lang_zh"),
                          ("en_US", "lang_en")):
            act = QAction(tr(key), self)
            act.setCheckable(True)
            self._lang_group.addAction(act)
            lang_menu.addAction(act)
            self._lang_actions[code] = act
            act.triggered.connect(lambda checked, c=code: self._set_language(c))

        help_menu = menubar.addMenu(tr("menu_help"))
        self._menus["menu_help"] = help_menu
        self._act_about = QAction(tr("act_about"), self)
        self._act_about.triggered.connect(self._about)
        help_menu.addAction(self._act_about)

        # 菜单词条绑定（语言切换实时重刷）
        for widget, key in (
            (self._act_new, "act_new_instance"),
            (self._act_import_image, "act_import_image"),
            (self._act_export_instance, "act_export_instance"),
            (self._act_import_instance, "act_import_instance"),
            (self._act_exit, "act_exit"),
            (self._act_global, "act_global_settings"),
            (self._act_instance, "act_instance_settings"),
            (self._act_guide, "act_vt_guide"),
            (self._act_about, "act_about"),
        ):
            bind(widget, key)
        for mode, key in (("system", "theme_system"), ("light", "theme_light"),
                          ("dark", "theme_dark")):
            bind(self._theme_actions[mode], key)
        for code, key in (("system", "lang_system"), ("zh_CN", "lang_zh"),
                          ("en_US", "lang_en")):
            bind(self._lang_actions[code], key)

    # ================================================================ toolbar
    def _build_toolbar(self) -> None:
        bar = QToolBar()
        bar.setMovable(False)
        self.addToolBar(bar)

        def add(key: str, callback, primary: bool = False, danger: bool = False) -> QPushButton:
            btn = QPushButton()
            bind(btn, key)
            if primary:
                btn.setObjectName("primary")
            if danger:
                btn.setObjectName("danger")
            btn.clicked.connect(callback)
            bar.addWidget(btn)
            return btn

        add("btn_new_instance", self._create_instance, primary=True)
        add("btn_batch_start", self._batch_start)
        add("btn_batch_stop", self._batch_stop)
        add("btn_batch_delete", self._batch_delete, danger=True)
        bar.addSeparator()
        add("btn_export_instance", self._export_instance)
        add("btn_import_instance", self._import_instance)
        add("btn_import_image", self._import_image)
        bar.addSeparator()
        add("btn_refresh", self._tick)

    # ================================================================ status bar
    def _build_status(self) -> None:
        self._vt_btn = QPushButton()
        self._vt_btn.setFlat(True)
        self._vt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._vt_btn.clicked.connect(self._open_vt_guide)
        self.statusBar().addWidget(self._vt_btn)
        self._summary_label = QLabel("")
        self.statusBar().addPermanentWidget(self._summary_label)

    # ================================================================ theme / language
    def _set_theme(self, mode: str) -> None:
        self._theme.set_mode(mode)

    def _set_language(self, code: str) -> None:
        self._service.settings.update(language=code)
        # 语言切换实时生效（翻译器由服务层监听设置变化）
        self._service.apply_language_setting()

    def _poll_theme(self) -> None:
        self._theme.poll_system()

    def _on_language_changed(self) -> None:
        self._set_table_headers()
        for key, menu in self._menus.items():
            menu.setTitle(tr(key))
        self._row_ids = []  # 强制重建行（按钮/徽章文本）
        self._tick()
        self.setWindowTitle(f"{tr('app_title')} v{self._service.version}")
        self._update_vt_status()

    # ================================================================ table
    def _set_table_headers(self) -> None:
        self._table.setHorizontalHeaderLabels([tr(c) for c in COLS])

    def _tick(self) -> None:
        instances = self._service.instances.list_instances()
        self._refresh_table(instances)
        self._update_summary(instances)
        self._update_vt_status()

    def _refresh_table(self, instances: List[Instance]) -> None:
        ids = [i.id for i in instances]
        if ids != self._row_ids:
            self._row_ids = list(ids)
            self._rows.clear()
            self._table.setRowCount(0)
            for inst in instances:
                self._append_row(inst)
        else:
            for row, inst in enumerate(instances):
                widgets = self._rows.get(inst.id)
                if widgets is None:
                    continue
                widgets["badge"].set_state(inst.state)
                start_btn = widgets["start_btn"]
                running = inst.state == InstanceState.RUNNING
                starting = inst.state == InstanceState.STARTING
                stopping = inst.state == InstanceState.STOPPING
                start_btn.setText(tr("btn_stop") if running else tr("btn_start"))
                start_btn.setEnabled(inst.state in (
                    InstanceState.STOPPED, InstanceState.ERROR,
                    InstanceState.RUNNING))
                if starting or stopping:
                    start_btn.setEnabled(False)

    def _append_row(self, inst: Instance) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(inst.name))
        badge = StatusBadge(inst.state)
        self._table.setCellWidget(row, 1, badge)
        self._table.setItem(row, 2, QTableWidgetItem(tr("cell_cpu", n=inst.config.cpu_cores)))
        self._table.setItem(row, 3, QTableWidgetItem(
            tr("cell_memory", gb=f"{inst.config.memory_mb / 1024:.1f}")))
        self._table.setItem(row, 4, QTableWidgetItem(tr("cell_disk", n=inst.config.disk_gb)))
        image = self._service.images.get(inst.image_id)
        version = f"Android {image.android_version}" if image else inst.image_id
        self._table.setItem(row, 5, QTableWidgetItem(version))
        self._table.setItem(row, 6, QTableWidgetItem(
            f"127.0.0.1:{inst.config.adb_port}" if inst.config.adb_port else "-"))

        actions = QWidget()
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        start_btn = QPushButton()
        start_btn.clicked.connect(lambda _c, iid=inst.id: self._toggle_start(iid))
        layout.addWidget(start_btn)
        display_btn = QPushButton()
        bind(display_btn, "btn_display")
        display_btn.clicked.connect(lambda _c, iid=inst.id: self._open_display(iid))
        layout.addWidget(display_btn)
        more_btn = QPushButton()
        bind(more_btn, "btn_more")
        more_btn.clicked.connect(lambda _c, iid=inst.id: self._show_row_menu(iid))
        layout.addWidget(more_btn)
        self._table.setCellWidget(row, len(COLS) - 1, actions)
        self._rows[inst.id] = {"badge": badge, "start_btn": start_btn}

    # ================================================================ actions
    def _current_instance(self) -> Optional[Instance]:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._row_ids):
            return None
        return self._service.instances.get(self._row_ids[row])

    def _toggle_start(self, instance_id: str) -> None:
        inst = self._service.instances.get(instance_id)
        if inst is None:
            return
        if inst.state == InstanceState.RUNNING:
            self._stop_instance(inst)
        else:
            self._start_instance(inst)

    def _start_instance(self, inst: Instance) -> None:
        self._pending_display.add(inst.id)
        self._service.instances.start(inst.id)
        self._tick()

    def _stop_instance(self, inst: Instance) -> None:
        self._service.instances.stop(inst.id, force=False)
        self._tick()

    def _batch_start(self) -> None:
        for inst in self._service.instances.list_instances():
            if inst.state in (InstanceState.STOPPED, InstanceState.ERROR):
                self._pending_display.add(inst.id)
                self._service.instances.start(inst.id)
        self._tick()

    def _batch_stop(self) -> None:
        running = [i for i in self._service.instances.list_instances()
                   if i.state in (InstanceState.RUNNING, InstanceState.STARTING)]
        for inst in running:
            self._service.instances.stop(inst.id, force=False)
        self._tick()

    def _batch_delete(self) -> None:
        selected = self._selected_instances()
        targets = selected or self._service.instances.list_instances()
        running = [i for i in targets if i.state in (
            InstanceState.RUNNING, InstanceState.STARTING, InstanceState.STOPPING)]
        if running:
            QMessageBox.warning(
                self, tr("msg_error"),
                tr("err_batch_delete_running", count=len(running)))
            return
        if not targets:
            return
        box = QMessageBox(
            QMessageBox.Icon.Warning, tr("dlg_confirm_delete_title"),
            tr("msg_confirm_batch_delete", count=len(targets)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.button(QMessageBox.StandardButton.Yes).setText(tr("btn_yes"))
        box.button(QMessageBox.StandardButton.No).setText(tr("btn_no"))
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        for inst in targets:
            try:
                self._service.instances.delete(inst.id)
            except Exception as exc:
                self._show_error_exc(exc)
        self._tick()

    def _show_error_exc(self, exc: Exception) -> None:
        key = getattr(exc, "key", None) or (exc.args[0] if exc.args else "err_unknown")
        detail = getattr(exc, "detail", "") or ""
        QMessageBox.warning(self, tr("msg_error"), tr(str(key)) +
                            (f"\n{detail[:300]}" if detail else ""))

    def _selected_instances(self) -> List[Instance]:
        rows = sorted(set(index.row() for index in self._table.selectedIndexes()))
        out = []
        for row in rows:
            if 0 <= row < len(self._row_ids):
                inst = self._service.instances.get(self._row_ids[row])
                if inst:
                    out.append(inst)
        return out

    def _show_row_menu(self, instance_id: str) -> None:
        inst = self._service.instances.get(instance_id)
        if inst is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("btn_screenshot"), lambda: self._screenshot(inst))
        menu.addAction(tr("btn_record") if inst.id not in self._recorders or
                       not self._recorders[inst.id].recording
                       else tr("btn_stop_record"),
                       lambda: self._toggle_record(inst))
        menu.addSeparator()
        menu.addAction(tr("act_instance_settings"),
                       lambda: InstanceSettingsDialog(self._service, inst, self).exec())
        menu.addAction(tr("btn_keymap"),
                       lambda: self._open_keymap(inst))
        menu.addAction(tr("btn_macro"),
                       lambda: MacroEditorDialog(self._service, inst, self).exec())
        menu.addSeparator()
        menu.addAction(tr("btn_push_file"), lambda: self._push_file(inst))
        menu.addAction(tr("btn_pull_file"), lambda: self._pull_file(inst))
        menu.addAction(tr("btn_sync_shared"), lambda: self._sync_shared(inst))
        menu.addSeparator()
        menu.addAction(tr("btn_backup"), lambda: self._backup(inst))
        menu.addAction(tr("btn_clone"), lambda: self._clone(inst))
        menu.addAction(tr("btn_copy"), lambda: self._copy(inst))
        menu.addAction(tr("btn_export_instance"), lambda: self._export_one(inst))
        menu.addSeparator()
        menu.addAction(tr("btn_delete"), lambda: self._delete_one(inst))
        menu.exec(QCursor.pos())

    # ------------------------------------------------------------- instance ops
    def _create_instance(self) -> None:
        dlg = CreateInstanceDialog(self._service, self)
        if dlg.exec() and dlg.created_instance is not None:
            created = dlg.created_instance
            box = QMessageBox(
                QMessageBox.Icon.Question, tr("dlg_start_now_title"),
                tr("msg_start_now", name=created.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
            box.button(QMessageBox.StandardButton.Yes).setText(tr("btn_yes"))
            box.button(QMessageBox.StandardButton.No).setText(tr("btn_no"))
            if box.exec() == QMessageBox.StandardButton.Yes:
                self._start_instance(self._service.instances.get(created.id)
                                     or created)
        self._tick()

    def _clone(self, inst: Instance) -> None:
        AsyncRunner(
            self, tr("msg_working"),
            lambda: self._service.instances.clone(inst.id),
            lambda new: self._after_generic("msg_clone_success",
                                            name=new.name, id=new.id)).start()

    def _copy(self, inst: Instance) -> None:
        AsyncRunner(
            self, tr("msg_working"),
            lambda: self._service.instances.copy(inst.id),
            lambda new: self._after_generic("msg_copy_success",
                                            name=new.name, id=new.id)).start()

    def _after_generic(self, key: str, **params) -> None:
        QMessageBox.information(self, tr("msg_done"), tr(key, **params))
        self._tick()

    def _delete_one(self, inst: Instance) -> None:
        if inst.state in (InstanceState.RUNNING, InstanceState.STARTING):
            QMessageBox.warning(self, tr("msg_error"), tr("err_instance_running"))
            return
        box = QMessageBox(
            QMessageBox.Icon.Warning, tr("dlg_confirm_delete_title"),
            tr("msg_confirm_delete", name=inst.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.button(QMessageBox.StandardButton.Yes).setText(tr("btn_yes"))
        box.button(QMessageBox.StandardButton.No).setText(tr("btn_no"))
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self._service.instances.delete(inst.id)
        self._tick()

    def _backup(self, inst: Instance) -> None:
        AsyncRunner(
            self, tr("msg_working"),
            lambda: self._service.instances.backup(inst.id),
            lambda path: self._after_generic("msg_backup_success", path=str(path))).start()

    def _export_one(self, inst: Instance) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, tr("btn_export_instance"), f"{inst.name}.zip", "ZIP (*.zip)")
        if not path:
            return
        AsyncRunner(
            self, tr("msg_working"),
            lambda: self._service.instances.export_instance(inst.id, path),
            lambda out: self._after_generic("msg_export_success", path=str(out))).start()

    def _export_instance(self) -> None:
        inst = self._current_instance()
        if inst is None:
            QMessageBox.information(self, tr("msg_tip"), tr("msg_select_instance_first"))
            return
        self._export_one(inst)

    def _import_instance(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, tr("act_import_instance"), "", "ZIP (*.zip)")
        if not path:
            return
        AsyncRunner(
            self, tr("msg_working"),
            lambda: self._service.instances.import_instance(path),
            lambda new: self._after_generic("msg_import_instance_success",
                                            name=new.name, id=new.id)).start()

    def _import_image(self) -> None:
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from mirror.image_manager import ImageManagerError
        path, _ = QFileDialog.getOpenFileName(
            self, tr("dlg_import_image"), "", "Image (image.json *.zip);;All (*)")
        if not path:
            return
        p = Path(path)
        src = p if (p.is_dir() or p.suffix.lower() == ".zip") else p.parent

        def job():
            return self._service.images.import_image(src)

        def done(img):
            self._after_generic("msg_image_imported", id=img.id)

        def fail_handler(detail: str):
            QMessageBox.warning(self, tr("msg_error"), detail[:400])

        AsyncRunner(self, tr("msg_working"), job, done, fail_handler).start()

    # ------------------------------------------------------------- display
    def _open_display(self, instance_id: str) -> None:
        inst = self._service.instances.get(instance_id)
        if inst is None:
            return
        if inst.state != InstanceState.RUNNING:
            QMessageBox.information(self, tr("msg_tip"), tr("err_instance_not_running"))
            return
        win = self._displays.get(inst.id)
        if win is None:
            win = DisplayWindow(self._service, inst)
            win.window_closed.connect(self._on_display_closed)
            self._displays[inst.id] = win
        win.show()
        win.raise_()
        win.activateWindow()
        if win.isMinimized():
            win.showNormal()

    def _on_display_closed(self, instance_id: str) -> None:
        self._displays.pop(instance_id, None)

    # ------------------------------------------------------------- tools ops
    def _screenshot(self, inst: Instance) -> None:
        from tools.screenshot import capture_screenshot

        def job():
            return capture_screenshot(
                self._service.adb, inst.config.adb_port, inst.name)

        def done(path):
            QMessageBox.information(self, tr("msg_screenshot_saved_title"),
                                    tr("msg_screenshot_saved", path=str(path)))

        AsyncRunner(self, tr("msg_working"), job, done).start()

    def _toggle_record(self, inst: Instance) -> None:
        recorder = self._recorders.get(inst.id)
        if recorder is None:
            from tools.recorder import ScreenRecorder
            recorder = ScreenRecorder(self._service.adb)
            self._recorders[inst.id] = recorder
        if recorder.recording:
            def job():
                return recorder.stop()

            def done(path):
                QMessageBox.information(self, tr("msg_record_saved_title"),
                                        tr("msg_record_saved", path=str(path)))

            AsyncRunner(self, tr("msg_working"), job, done).start()
        else:
            recorder.start(inst.config.adb_port, inst.name)
            QMessageBox.information(self, tr("msg_tip"), tr("msg_recording"))

    def _push_file(self, inst: Instance) -> None:
        from PySide6.QtWidgets import QFileDialog
        local, _ = QFileDialog.getOpenFileName(self, tr("btn_push_file"))
        if not local:
            return
        from PySide6.QtWidgets import QInputDialog
        remote, ok = QInputDialog.getText(
            self, tr("btn_push_file"), "/sdcard/", text="/sdcard/")
        if not ok:
            return
        AsyncRunner(
            self, tr("msg_working"),
            lambda: sync_tool.push_file(
                self._service.adb, inst.config.adb_port, local, remote),
            lambda ok_: self._after_generic("msg_push_done") if ok_ else
            self._after_generic("err_transfer_failed")).start()

    def _pull_file(self, inst: Instance) -> None:
        import os
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        remote, ok = QInputDialog.getText(
            self, tr("btn_pull_file"), "/sdcard/", text="/sdcard/Download/")
        if not ok:
            return
        local = QFileDialog.getExistingDirectory(self, tr("btn_pull_file"))
        if not local:
            return
        target = os.path.join(local, os.path.basename(remote.rstrip("/")))
        AsyncRunner(
            self, tr("msg_working"),
            lambda: sync_tool.export_guest_file(
                self._service.adb, inst.config.adb_port, remote, target),
            lambda ok_: self._after_generic("msg_pull_done") if ok_ else
            self._after_generic("err_transfer_failed")).start()

    def _sync_shared(self, inst: Instance) -> None:
        sf = sync_tool.default_sync(self._service.adb, self._service.settings)

        def job():
            return sf.sync_bidirectional(inst.config.adb_port)

        def done(counts):
            self._after_generic("msg_sync_done", pushed=counts[0], pulled=counts[1])

        AsyncRunner(self, tr("msg_working"), job, done).start()

    def _open_keymap(self, inst: Instance) -> None:
        dlg = KeymapEditorDialog(self._service, inst, self)
        if dlg.exec():
            profile = dlg.collect_profile()
            win = self._displays.get(inst.id)
            if win is not None:
                win.set_keymap(profile, True)

    # ------------------------------------------------------------- settings
    def _open_global_settings(self) -> None:
        GlobalSettingsDialog(self._service, self).exec()
        self._tick()

    def _open_selected_settings(self) -> None:
        inst = self._current_instance()
        if inst is None:
            QMessageBox.information(self, tr("msg_tip"), tr("msg_select_instance_first"))
            return
        InstanceSettingsDialog(self._service, inst, self).exec()
        self._tick()

    def _open_vt_guide(self) -> None:
        VirtualizationGuideDialog(self._service, self,
                                  on_recheck=self._tick).exec()
        self._tick()

    def _about(self) -> None:
        QMessageBox.about(
            self, tr("act_about"),
            f"<h3 style='color:#1677FF;'>{tr('app_title')} v{self._service.version}</h3>"
            f"<p>{tr('about_text')}</p>")

    # ------------------------------------------------------------- events
    def _on_instance_event(self, instance_id: str, state: str,
                           error_key: str, detail: str) -> None:
        self._tick()
        if state == InstanceState.RUNNING and instance_id in self._pending_display:
            self._pending_display.discard(instance_id)
            self._open_display(instance_id)
        if state == InstanceState.ERROR and error_key:
            inst = self._service.instances.get(instance_id)
            name = inst.name if inst else instance_id
            box = QMessageBox(QMessageBox.Icon.Critical, tr("dlg_start_failed_title"),
                              tr("msg_start_failed", name=name, reason=tr(error_key)),
                              parent=self)
            box.setDetailedText(detail[-800:])
            box.addButton(tr("btn_close"), QMessageBox.ButtonRole.AcceptRole)
            box.exec()

    # ------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and all(u.isLocalFile() and u.toLocalFile().lower().endswith(".apk")
                        for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        apks = [u.toLocalFile() for u in event.mimeData().urls()]
        if not apks:
            return
        running = [i for i in self._service.instances.list_instances()
                   if i.state == InstanceState.RUNNING]
        if not running:
            QMessageBox.information(self, tr("msg_tip"), tr("msg_no_running_instance"))
            return
        names = [i.name for i in running]
        dlg = InstallPickerDialog(self, names, len(apks))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = set(dlg.checked())
        targets = [i for i in running if i.name in chosen]
        if not targets:
            return

        def job():
            count = 0
            for inst in targets:
                port = inst.config.adb_port
                self._service.adb.connect(port)
                for apk in apks:
                    self._service.adb.install(port, apk)
                    count += 1
            return count

        def done(count: int):
            self._after_generic("msg_install_success_count", count=count)

        AsyncRunner(self, tr("msg_installing"), job, done).start()

    # ------------------------------------------------------------- status
    def _update_summary(self, instances: List[Instance]) -> None:
        running = [i for i in instances if i.state == InstanceState.RUNNING]
        cpu = sum(i.config.cpu_cores for i in running)
        mem = sum(i.config.memory_mb for i in running) / 1024.0
        thresholds = self._service.guard.thresholds()
        self._summary_label.setText(tr(
            "status_summary",
            total=len(instances), running=len(running),
            cpu=cpu, cpu_max=thresholds.max_total_cpu_cores,
            mem=round(mem, 1), mem_max=thresholds.max_total_memory_gb))

    def _update_vt_status(self) -> None:
        vt = self._service.qemu.virtualization()
        if vt.accelerated:
            self._vt_btn.setText(f"✔ {tr('vt_status_enabled')}")
            self._vt_btn.setStyleSheet(
                f"color: {SUCCESS_COLOR}; border: none; padding: 2px 8px;")
            if self._banner.isVisible():
                self._banner.hide()
        else:
            self._vt_btn.setText(f"⚠ {tr('vt_status_disabled')}")
            self._vt_btn.setStyleSheet(
                f"color: {WARNING_COLOR}; border: none; padding: 2px 8px;")
            if not self._banner_shown:
                self._banner_shown = True
                self._banner.show()
        for mode, act in self._theme_actions.items():
            act.setChecked(mode == self._theme.mode)
        for code, act in self._lang_actions.items():
            act.setChecked(code == self._service.settings.get().language)

    def _startup_check(self) -> None:
        vt = self._service.qemu.virtualization()
        if not vt.accelerated:
            self._banner_shown = True
            self._banner.show()
            QTimer.singleShot(300, self._open_vt_guide)

    # ------------------------------------------------------------- close
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        for win in list(self._displays.values()):
            win.close()
        super().closeEvent(event)
