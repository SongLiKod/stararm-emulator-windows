# 获取 QEMU 8.2+ Windows x64 官方构建（含 qemu-system-aarch64 与 qemu-img），
# 内置封装到部署包 qemu/ 目录（底层 QEMU 组件内置封装、免配置一键部署）。
# 下载源：Stefan Weil 官方分发（https://qemu.weilnetz.de/w64/），站点只保留近期安装包，
# 旧固定链接会 404，因此默认按候选列表逐个尝试，并从目录索引自动发现最新安装包。
param(
    [Parameter(Mandatory = $false)]
    [string]$Destination = ".\qemu",
    # 指定下载地址（留空则自动选择：先固定 8.2.0 稳定版，再回退到索引中最新安装包）
    [Parameter(Mandatory = $false)]
    [string]$Url = ""
)

$ErrorActionPreference = "Stop"

$IndexUrl = "https://qemu.weilnetz.de/w64/"

# 候选下载地址（按优先级）：文档要求 QEMU 8.2+，固定 8.2.0 稳定版为首选
$Candidates = @()
if ($Url) { $Candidates += $Url }
$Candidates += "https://qemu.weilnetz.de/w64/2023/qemu-w64-setup-20231224.exe"  # QEMU 8.2.0

# 从目录索引发现当前可用安装包（最新在后，逆序加入优先新版本）
try {
    $Index = (Invoke-WebRequest -Uri $IndexUrl -UseBasicParsing).Content
    $Names = [regex]::Matches($Index, 'qemu-w64-setup-\d{8}\.exe') |
        ForEach-Object { $_.Value } | Sort-Object -Unique
    foreach ($n in ($Names | Sort-Object -Descending)) {
        $Candidates += "$IndexUrl$n"
    }
} catch {
    Write-Host "[fetch_qemu] index discovery failed: $($_.Exception.Message)"
}
$Candidates = $Candidates | Select-Object -Unique
if (-not $Candidates) { throw "no QEMU download candidates" }

$TempDir = Join-Path $env:TEMP "stararm-qemu-$(Get-Random)"
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
$Installer = Join-Path $TempDir "qemu-setup.exe"

$Downloaded = $false
foreach ($Cand in $Candidates) {
    Write-Host "[fetch_qemu] Downloading QEMU ($Cand)..."
    try {
        Invoke-WebRequest -Uri $Cand -OutFile $Installer -UseBasicParsing
        # 校验下载结果：安装包约 165MB，过小说明拿到的是错误页/残缺文件
        $Size = (Get-Item $Installer).Length
        if ($Size -gt 50MB) { $Downloaded = $true; break }
        Write-Host "[fetch_qemu] suspicious size ($Size bytes), trying next candidate..."
    } catch {
        Write-Host "[fetch_qemu] download failed: $($_.Exception.Message)"
    }
}
if (-not $Downloaded) {
    Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
    throw "all QEMU download candidates failed"
}

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
Get-ChildItem -Path $DestFull -Recurse -Filter "*.exe" | Where-Object {
    $_.Name -notin $Keep
} | Remove-Item -Force -ErrorAction SilentlyContinue

Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
Write-Host "[fetch_qemu] Done -> $DestFull"
