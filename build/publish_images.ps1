# 把本地镜像目录打包为镜像源约定的 zip，并（可选）发布到 GitHub Release「images」，
# 使内置镜像源立即可用（GitHub Releases 及其国内加速源 ghfast.top 会同步生效）。
#
# 前置：
#   1) 本地已有镜像目录（含 image.json + Image + system.img …，ARM64）
#   2) 本机 git 凭据管理器中存有 github.com 的访问令牌（可写仓库）
#
# 用法：
#   ./build/publish_images.ps1 -ImageDir C:\images\aosp-13-arm64
#   ./build/publish_images.ps1 -ImageDir C:\images\aosp-13-arm64 -ZipOnly   # 只打包不上传
#   ./build/publish_images.ps1 -ImageDir C:\images\aosp-13-arm64 -SkipHf    # 只发 GitHub
# HuggingFace（hf-mirror.com / huggingface.co 两条源）需要 HF_TOKEN：
#   setx HF_TOKEN hf_xxx      # 网站 Settings → Access Tokens → New token（write 权限）
param(
    [Parameter(Mandatory = $true)]
    [string]$ImageDir,
    [switch]$ZipOnly,
    [switch]$SkipHf,
    [string]$HfToken = "",
    [string]$Python = "",
    [string]$OutDir = (Join-Path $env:TEMP "stararm-image-publish"),
    [string]$Owner = "SongLiKod",
    [string]$Repo = "stararm-emulator-windows"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ImageDir = (Resolve-Path $ImageDir).Path

$Manifest = Join-Path $ImageDir "image.json"
if (-not (Test-Path $Manifest)) { throw "image.json not found in $ImageDir" }
$ImageId = (Get-Content $Manifest -Raw | ConvertFrom-Json).id
if (-not $ImageId) { throw "image.json has no id" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$ZipPath = Join-Path $OutDir "$ImageId.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $ImageDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host "[publish] packed $ZipPath ($([math]::Round((Get-Item $ZipPath).Length/1MB,1)) MB)"
if ($ZipOnly) { Write-Host "[publish] -ZipOnly, skip upload."; exit 0 }

# 从 git 凭据管理器取 github.com 令牌（不回显）
$Cred = "protocol=https`nhost=github.com`n`n" | git credential fill 2>$null
$Token = ($Cred | Where-Object { $_ -like "password=*" }) -replace "^password=", ""
$User = ($Cred | Where-Object { $_ -like "username=*" }) -replace "^username=", ""
if (-not $Token) { throw "No github.com credential found (git credential fill)." }
$Headers = @{
    "Authorization" = "Bearer $Token"
    "Accept" = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent" = "stararm-publish"
}

# 幂等：存在 tag=images 的 release 则复用，否则创建
$Release = $null
try { $Release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/releases/tags/images" -Headers $Headers } catch { }
if (-not $Release) {
    $Body = @{ tag_name = "images"; name = "内置镜像源（AOSP ARM64）"; draft = $false; prerelease = $false } | ConvertTo-Json
    $Release = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$Owner/$Repo/releases" -Headers $Headers -Body $Body -ContentType "application/json"
    Write-Host "[publish] created release images (id=$($Release.id))"
}

$Existing = @($Release.assets | ForEach-Object { $_.name })
if ($Existing -contains "$ImageId.zip") {
    Invoke-RestMethod -Method Delete -Uri "https://api.github.com/repos/$Owner/$Repo/releases/assets/$((@($Release.assets) | Where-Object { $_.name -eq "$ImageId.zip" }).id)" -Headers $Headers | Out-Null
    Write-Host "[publish] removed old asset $ImageId.zip"
}

$UploadUrl = "https://uploads.github.com/repos/$Owner/$Repo/releases/$($Release.id)/assets?name=$([uri]::EscapeDataString("$ImageId.zip"))"
Write-Host "[publish] uploading $ImageId.zip ..."
$Asset = Invoke-RestMethod -Method Post -Uri $UploadUrl -Headers $Headers -InFile $ZipPath -ContentType "application/zip"
Write-Host "[publish] done: $($Asset.browser_download_url)"
Write-Host "[publish] sources now serving it: GitHub Releases + ghfast.top (国内加速)"

if ($SkipHf) { Write-Host "[publish] -SkipHf, skip HuggingFace upload."; exit 0 }
if (-not $HfToken) { $HfToken = $env:HF_TOKEN }
if (-not $HfToken) {
    Write-Warning "未提供 HF_TOKEN，HuggingFace 未上传（hf-mirror.com / huggingface.co 仍不可用）。获取: https://huggingface.co/settings/tokens 新建 write 权限 token，然后 setx HF_TOKEN hf_xxx 后重跑本脚本，或本次显式传 -SkipHf。"
    exit 0
}

if (-not $Python) {
    foreach ($cand in @($env:STARARM_PYTHON, "python", "py -3")) {
        if ($cand) { try { & $cand --version *> $null; if ($LASTEXITCODE -eq 0 -or $?) { $Python = $cand; break } } catch { } }
    }
}
if (-not $Python) { throw "未找到 Python，用 -Python <可执行文件> 指定" }
$env:HF_TOKEN = $HfToken
Write-Host "[publish] uploading to HuggingFace ..."
& $Python (Join-Path $PSScriptRoot "upload_hf.py") $ZipPath
if ($LASTEXITCODE -ne 0) { throw "HuggingFace upload failed (exit $LASTEXITCODE)" }
Write-Host "[publish] all 4 sources enabled."
