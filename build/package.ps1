# 星模ARM原生安卓模拟器 - 打包部署脚本
# 产物：release/StarARM-win64-<version>.zip（绿色免配置一键部署）
# 可选：-WithQemu / -WithAdb 内置封装底层 QEMU 与 ADB 组件
param(
    [switch]$WithQemu,
    [switch]$WithAdb,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# 读取版本号
$Constants = Get-Content (Join-Path $RepoRoot "config\constants.py") -Raw -Encoding UTF8
if ($Constants -match 'VERSION\s*=\s*"([^"]+)"') { $Version = $Matches[1] } else { $Version = "1.0.0" }

Write-Host "[package] Installing dependencies..."
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "[package] Building with PyInstaller..."
& $Python -m PyInstaller build\stararm.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

# 组装绿色部署目录
$ReleaseDir = Join-Path $RepoRoot "release\StarARM-win64-$Version"
if (Test-Path $ReleaseDir) { Remove-Item -Recurse -Force $ReleaseDir }
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

Copy-Item -Path (Join-Path $RepoRoot "dist\StarARM\*") -Destination $ReleaseDir -Recurse
Copy-Item -Path (Join-Path $RepoRoot "dist\stararm-cli.exe") -Destination $ReleaseDir

# 内置镜像存储目录（空目录随包，内置镜像可通过 fetch_images.ps1 获取）
New-Item -ItemType Directory -Force -Path (Join-Path $ReleaseDir "mirror\images") | Out-Null

if ($WithQemu) {
    Write-Host "[package] Bundling QEMU..."
    & (Join-Path $PSScriptRoot "fetch_qemu.ps1") -Destination (Join-Path $ReleaseDir "qemu")
}
if ($WithAdb) {
    Write-Host "[package] Bundling ADB..."
    & (Join-Path $PSScriptRoot "fetch_adb.ps1") -Destination (Join-Path $ReleaseDir "adb-runtime")
}

Write-Host "[package] Creating zip..."
$Zip = Join-Path $RepoRoot "release\StarARM-win64-$Version.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path (Join-Path $ReleaseDir "*") -DestinationPath $Zip

Write-Host "[package] Done -> $Zip"
Write-Host "[package] Qt Installer Framework 打包（可选）："
Write-Host "  binarycreator -c build/installer/config.xml -p build/installer/packages StarARMInstaller.exe"
