# 下载 Windows 版 ffmpeg 可执行文件到 tools/ffmpeg/bin（供手心语 Kimi 压缩视频）
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$BinDir = Join-Path $Root "tools\ffmpeg\bin"
$Exe = Join-Path $BinDir "ffmpeg.exe"
if (Test-Path $Exe) {
    Write-Host "已存在: $Exe"
    & $Exe -version | Select-Object -First 1
    exit 0
}
$ZipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$TmpZip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
$TmpDir = Join-Path $env:TEMP "ffmpeg-extract-$(Get-Random)"
Write-Host "正在下载 ffmpeg ..."
Invoke-WebRequest -Uri $ZipUrl -OutFile $TmpZip -UseBasicParsing
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
Expand-Archive -Path $TmpZip -DestinationPath $TmpDir -Force
$Found = Get-ChildItem -Path $TmpDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $Found) { throw "解压后未找到 ffmpeg.exe" }
Copy-Item $Found.FullName $Exe -Force
$Ffprobe = Join-Path $Found.DirectoryName "ffprobe.exe"
if (Test-Path $Ffprobe) { Copy-Item $Ffprobe (Join-Path $BinDir "ffprobe.exe") -Force }
Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
Remove-Item $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "安装完成: $Exe"
& $Exe -version | Select-Object -First 1
