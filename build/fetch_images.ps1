# 从镜像源下载内置标准 AOSP ARM64 镜像（Android 11-15）并导入用户数据目录。
# 镜像源 URL 来自全局设置（settings.json 的 image_source），也可用 -ImageSource 覆盖。
param(
    [Parameter(Mandatory = $false)]
    [string]$ImageSource = "",
    [Parameter(Mandatory = $false)]
    [string[]]$Images = @(
        "aosp-11-arm64", "aosp-12-arm64", "aosp-13-arm64",
        "aosp-14-arm64", "aosp-15-arm64"
    )
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if (-not $ImageSource) {
    # 从全局设置读取镜像源
    $Settings = Join-Path $env:APPDATA "StarARM\settings.json"
    if (Test-Path $Settings) {
        $Json = Get-Content $Settings -Raw | ConvertFrom-Json
        $ImageSource = $Json.image_source
    }
}
if (-not $ImageSource) {
    throw "No image source configured. Pass -ImageSource or set image_source in settings."
}

foreach ($Image in $Images) {
    Write-Host "[fetch_images] $Image ..."
    python -m adb.cli download-image --image $Image
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "[fetch_images] Failed to download $Image"
    }
}
Write-Host "[fetch_images] Done."
