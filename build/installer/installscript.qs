// Qt Installer Framework 安装脚本：桌面/开始菜单快捷方式
function Component() {}

Component.prototype.createOperations = function () {
    component.createOperations();
    if (installer.value("os") === "win") {
        component.addOperation("CreateShortcut",
            "@TargetDir@/StarARM.exe",
            "@DesktopDir@/StarARM.lnk",
            "workingDirectory=@TargetDir@");
        component.addOperation("CreateShortcut",
            "@TargetDir@/StarARM.exe",
            "@StartMenuDir@/StarARM.lnk",
            "workingDirectory=@TargetDir@");
    }
};
