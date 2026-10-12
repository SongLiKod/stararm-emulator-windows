# 从镜像源下载内置标准 AOSP ARM64 镜像（Android 11-15）并导入用户数据目录。
#
# 源选择逻辑与 GUI 一致（见全局设置「镜像源」与 resource/image_sources.json）：
#   - 默认「自动」：内置源逐个尝试（国内 ghfast.top / hf-mirror.com，海外 GitHub Releases / Hugging Face）
#   - 全局设置固定某一条内置源、或选择「自定义 URL」时按其下载
#   - -ImageSource <url>：临时改用自定义 URL（写入 settings.json，覆盖为“自定义”）
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
$Settings = Join-Path $env:APPDATA "StarARM\settings.json"

function Set-JsonProp($Object, [string]$Name, [string]$Value) {
    if ($Object.PSObject.Properties[$Name]) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

if ($ImageSource) {
    $Json = [PSCustomObject]@{}
    if (Test-Path $Settings) {
        try { $Json = Get-Content $Settings -Raw | ConvertFrom-Json } catch { $Json = [PSCustomObject]@{} }
    }
    Set-JsonProp $Json "image_source" $ImageSource
    Set-JsonProp $Json "image_source_id" "custom"
    $Text = $Json | ConvertTo-Json -Depth 10
    # 无 BOM 写入（Python json.loads 读取 settings.json 不接受 BOM）
    [System.IO.File]::WriteAllText($Settings, $Text, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "[fetch_images] custom source: $ImageSource"
}
elseif (Test-Path $Settings) {
    try {
        $Json = Get-Content $Settings -Raw | ConvertFrom-Json
        $Mode = if ($Json.image_source_id) { $Json.image_source_id } else { "auto" }
        if ($Mode -eq "custom" -and -not $Json.image_source) {
            Write-Warning "[fetch_images] settings selected Custom URL but none is set - falling back to built-in sources."
        }
        Write-Host "[fetch_images] source mode: $Mode"
    } catch { }
}

foreach ($Image in $Images) {
    Write-Host "[fetch_images] $Image ..."
    python -m adb.cli download-image --image $Image
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "[fetch_images] Failed to download $Image"
    }
}
Write-Host "[fetch_images] Done."
