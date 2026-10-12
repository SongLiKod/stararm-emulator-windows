# 获取原生 adb（Google 官方 platform-tools），内置封装到部署包 adb-runtime/
param(
    [Parameter(Mandatory = $false)]
    [string]$Destination = ".\adb-runtime"
)

$ErrorActionPreference = "Stop"
$Url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
$TempDir = Join-Path $env:TEMP "stararm-platform-tools-$(Get-Random)"

Write-Host "[fetch_adb] Downloading platform-tools (adb)..."
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
$Zip = Join-Path $TempDir "platform-tools.zip"
Invoke-WebRequest -Uri $Url -OutFile $Zip

Write-Host "[fetch_adb] Extracting..."
Expand-Archive -Path $Zip -DestinationPath $TempDir -Force

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
foreach ($file in @("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")) {
    $src = Join-Path $TempDir "platform-tools\$file"
    if (Test-Path $src) {
        Copy-Item $src -Destination (Join-Path $Destination $file) -Force
        Write-Host "[fetch_adb] Installed $file"
    }
}

Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
Write-Host "[fetch_adb] Done -> $Destination"
