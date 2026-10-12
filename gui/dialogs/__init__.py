"""GUI 对话框：新建实例、实例设置、全局设置、虚拟化教程、宏脚本、键位/手柄映射。"""
from gui.dialogs.create_instance import CreateInstanceDialog
from gui.dialogs.global_settings import GlobalSettingsDialog
from gui.dialogs.instance_settings import InstanceSettingsDialog
from gui.dialogs.keymap_editor import KeymapEditorDialog
from gui.dialogs.macro_editor import MacroEditorDialog
from gui.dialogs.quick_start import QuickStartDialog
from gui.dialogs.virtualization_guide import VirtualizationGuideDialog

__all__ = [
    "CreateInstanceDialog", "GlobalSettingsDialog", "InstanceSettingsDialog",
    "KeymapEditorDialog", "MacroEditorDialog", "QuickStartDialog",
    "VirtualizationGuideDialog",
]
