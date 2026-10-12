# 获取 QEMU 8.2+ Windows x64 官方构建（含 qemu-system-aarch64 与 qemu-img），
# 内置封装到部署包 qemu/ 目录（底层 QEMU 组件内置封装、免配置一键部署）。
param(
    [Parameter(Mandatory = $false)]
    [string]$Destination = ".\qemu",
    # QEMU 官方 Windows 构建（Stefan Weil 分发），默认 8.2 稳定版
    [Parameter(Mandatory = $false)]
    [string]$Url = "https://qemu.weilnetz.de/w64/2024/qemu-w64-setup-20240206.exe"
)

$ErrorActionPreference = "Stop"

Write-Host "[fetch_qemu] Downloading QEMU ($Url)..."
$TempDir = Join-Path $env:TEMP "stararm-qemu-$(Get-Random)"
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
$Installer = Join-Path $TempDir "qemu-setup.exe"
Invoke-WebRequest -Uri $Url -OutFile $Installer

$DestFull = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $DestFull | Out-Null

$SevenZip = Get-Command "7z" -ErrorAction SilentlyContinue
if ($SevenZip) {
    Write-Host "[fetch_qemu] Extracting with 7z..."
    & 7z x $Installer "-o$DestFull" -y | Out-Null
} else {
    # NSIS 静默安装到目标目录
    Write-Host "[fetch_qemu] Silent install (NSIS /S)..."
    $p = Start-Process -FilePath $Installer -ArgumentList "/S", "/D=$DestFull" -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        throw "QEMU installer exited with code $($p.ExitCode)"
    }
}

$QemuBin = Join-Path $DestFull "qemu-system-aarch64.exe"
if (-not (Test-Path $QemuBin)) {
    # 部分构建在根目录外多一层目录
    $Nested = Get-ChildItem -Path $DestFull -Recurse -Filter "qemu-system-aarch64.exe" |
        Select-Object -First 1
    if ($Nested) { $QemuBin = $Nested.FullName }
}
if (-not (Test-Path $QemuBin)) {
    throw "qemu-system-aarch64.exe not found after extraction"
}
Write-Host "[fetch_qemu] OK -> $QemuBin"

# 仅保留 ARM64 仿真必需组件（减小体积）
$Keep = @(
    "qemu-system-aarch64.exe", "qemu-img.exe",
    "libqemuutil.dll", "libqemuutil-x86_64.dll"
)
Get-ChildItem -Path $DestFull -Filter "*.exe" | Where-Object {
    $_.Name -notin $Keep
} | Remove-Item -Force -ErrorAction SilentlyContinue

Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
Write-Host "[fetch_qemu] Done -> $DestFull"
