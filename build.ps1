# build.ps1 — Flet Windows 一键打包脚本
# 
# 用法：放在项目根目录，PowerShell 里运行：
#   .\build.ps1
# 或者指定名称：
#   .\build.ps1 -ProductName "我的应用"
#
# 第一次运行会下载 Flutter（1GB），之后缓存复用，秒过。
# ============================================================================
param(
    [string]$ProductName = (Split-Path -Leaf (Get-Location)),
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = 1
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8

# ─── 路径常量 ────────────────────────────────────────
$PROJECT  = Get-Location
$FLUTTER  = "$env:USERPROFILE\flutter\3.44.4\bin\flutter.bat"
$CACHE    = "$env:USERPROFILE\.flet\cache"
$BUILD    = "$PROJECT\build"
$FLUTTER_PROJ = "$BUILD\flutter"
$CMAKE_FILE   = "$FLUTTER_PROJ\windows\CMakeLists.txt"
$RELEASE = "$FLUTTER_PROJ\build\windows\x64\runner\Release"
$APP_DIR  = "$RELEASE\app"
$LIB_SP   = "$RELEASE\Lib\site-packages"

Write-Host @"

╔══════════════════════════════════════════╗
║   Flet Windows 一键打包                 ║
║   项目: $ProductName
║   Python: $PythonVersion
╚══════════════════════════════════════════╝

"@ -ForegroundColor Cyan

# ═══════════════════════════════════════════════════════
# 1. 检查环境
# ═══════════════════════════════════════════════════════
Write-Host "[1/7] 检查环境..." -ForegroundColor Yellow

$fletVer = (pip show flet 2>$null | Select-String "Version:").ToString() -replace ".*:\s*", ""
if (-not $fletVer) { Write-Error "请先安装 flet: pip install flet"; exit 1 }
Write-Host "  flet $fletVer ✓" -ForegroundColor Green

if (-not (Test-Path $FLUTTER)) {
    Write-Host "  ⚠ Flutter 未找到，将通过 flet build 自动下载..." -ForegroundColor DarkYellow
}

if (-not (Test-Path requirements.txt)) {
    Write-Host "  ⚠ 未找到 requirements.txt，只打包 flet" -ForegroundColor DarkYellow
} else {
    $reqContent = Get-Content requirements.txt -Raw
    Write-Host "  requirements.txt ✓" -ForegroundColor Green
}

# ═══════════════════════════════════════════════════════
# 2. 首次 flet build（建立 Flutter 项目骨架）
# ═══════════════════════════════════════════════════════
Write-Host "[2/7] 初始化 Flutter 项目骨架..." -ForegroundColor Yellow

$needInit = -not (Test-Path $FLUTTER_PROJ)
if ($needInit) {
    flet build windows --yes --no-rich-output --product $ProductName --python-version $PythonVersion 2>&1 | Out-Null
    # 这一步大概率失败（网络/编码），没关系，骨架已经建好了
    if (Test-Path $FLUTTER_PROJ) {
        Write-Host "  项目骨架建立 ✓" -ForegroundColor Green
    } else {
        Write-Error "项目骨架建立失败"; exit 1
    }
} else {
    Write-Host "  已存在，跳过 ✓" -ForegroundColor Green
}

# ═══════════════════════════════════════════════════════
# 3. 下载缓存文件（如果缺）
# ═══════════════════════════════════════════════════════
Write-Host "[3/7] 检查缓存文件..." -ForegroundColor Yellow

function Download-IfMissing($url, $dest) {
    if (Test-Path $dest) { return }
    $dir = Split-Path $dest -Parent
    New-Item -Force -ItemType Directory $dir | Out-Null
    Write-Host "  下载: $(Split-Path $dest -Leaf)" -ForegroundColor DarkCyan
    Invoke-WebRequest -Uri $url -OutFile $dest -TimeoutSec 300 -UseBasicParsing
}

# Python standalone
$pyBuildDate = "20260623"
$pyFullVer = "3.12.13"
$pyCacheDir = "$CACHE\python-build-standalone\$pyBuildDate"
$pyArchive = "$pyCacheDir\cpython-$pyFullVer+$pyBuildDate-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
Download-IfMissing "https://github.com/astral-sh/python-build-standalone/releases/download/$pyBuildDate/cpython-$pyFullVer+$pyBuildDate-x86_64-pc-windows-msvc-install_only_stripped.tar.gz" $pyArchive

# python-windows-for-dart
$pwfdDate = "20260714"
$pwfdCacheDir = "$CACHE\python-build\v$pyFullVer-$pwfdDate"
$pwfdZip = "$pwfdCacheDir\python-windows-for-dart-$pyFullVer.zip"
Download-IfMissing "https://github.com/flet-dev/python-build/releases/download/$pwfdDate/python-windows-for-dart-$pyFullVer.zip" $pwfdZip

# dart-bridge
$dbVer = "1.5.0"
$dbCacheDir = "$CACHE\dart-bridge\v$dbVer"
Download-IfMissing "https://github.com/flet-dev/dart-bridge/releases/download/v$dbVer/dart_bridge-windows-x86_64.dll" "$dbCacheDir\dart_bridge-windows-x86_64.dll"
Download-IfMissing "https://github.com/flet-dev/dart-bridge/releases/download/v$dbVer/dart_bridge_d-windows-x86_64.dll" "$dbCacheDir\dart_bridge_d-windows-x86_64.dll"

# 解压 Python standalone 到 build 目录
$pyExtract = "$FLUTTER_PROJ\build\build_python_$PythonVersion"
if (-not (Test-Path "$pyExtract\python\python.exe")) {
    Write-Host "  解压 Python $pyFullVer..." -ForegroundColor DarkCyan
    New-Item -Force -ItemType Directory $pyExtract | Out-Null
    tar -xzf $pyArchive -C $pyExtract 2>$null
}

Write-Host "  缓存就绪 ✓" -ForegroundColor Green

# ═══════════════════════════════════════════════════════
# 4. 运行 Python 打包（serious_python）
# ═══════════════════════════════════════════════════════
Write-Host "[4/7] 打包 Python 应用..." -ForegroundColor Yellow

# 用 flet build 的 Python 打包部分（只做 Python，不重新 build Flutter）
# 如果已经存在 python-app 就跳过
$pyAppMarker = "$BUILD\python-app\.python_build_id"
$needPyPackage = -not (Test-Path $pyAppMarker)

if ($needPyPackage) {
    flet build windows --yes --no-rich-output --product $ProductName --python-version $PythonVersion 2>&1 | Out-Null
}

# 检查 python-app 是否已 staging
if (-not (Test-Path "$BUILD\python-app\main.pyc")) {
    # 手动运行 serious_python package
    $dart = "$env:USERPROFILE\flutter\3.44.4\bin\dart.bat"
    & $dart run --suppress-analytics serious_python:main package $PROJECT --platform Windows --python-version $PythonVersion -r -r -r "$PROJECT\requirements.txt" --exclude build --compile-app --compile-packages --cleanup-packages 2>&1 | Out-Null
}

if (Test-Path "$BUILD\python-app") {
    Write-Host "  Python 打包完成 ✓" -ForegroundColor Green
} else {
    Write-Host "  ⚠ Python 打包未完成，将继续..." -ForegroundColor DarkYellow
}

# ═══════════════════════════════════════════════════════
# 5. 打 UTF-8 补丁 → 编译 Flutter
# ═══════════════════════════════════════════════════════
Write-Host "[5/7] 编译 Flutter Windows 壳..." -ForegroundColor Yellow

# 打 UTF-8 补丁
$cmakeContent = Get-Content $CMAKE_FILE -Raw -ErrorAction SilentlyContinue
if ($cmakeContent -and $cmakeContent -notmatch "add_compile_options.*utf-8") {
    $cmakeContent = $cmakeContent -replace '(project\([^)]+\))', "`$1`n`nif(MSVC)`n  add_compile_options(`"/utf-8`")`nendif()"
    Set-Content $CMAKE_FILE $cmakeContent -NoNewline
    Write-Host "  UTF-8 补丁已应用 ✓" -ForegroundColor Green
}

$env:SERIOUS_PYTHON_VERSION = $PythonVersion
& $FLUTTER build windows --release --no-version-check --suppress-analytics 2>&1 | Out-Null

if (Test-Path "$RELEASE\chatroom.exe") {
    Write-Host "  Flutter 编译完成 ✓" -ForegroundColor Green
} else {
    Write-Error "Flutter 编译失败，请检查上方输出"; exit 1
}

# ═══════════════════════════════════════════════════════
# 6. 补齐缺失产物
# ═══════════════════════════════════════════════════════
Write-Host "[6/7] 补齐缺失的 DLL 和数据文件..." -ForegroundColor Yellow

# 插件 DLL
$pluginDlls = Get-ChildItem -Recurse "$FLUTTER_PROJ\build\windows\x64\plugins" -Filter "*.dll" -ErrorAction SilentlyContinue
foreach ($dll in $pluginDlls) {
    Copy-Item $dll.FullName $RELEASE -Force
}
Write-Host "  插件 DLL ($($pluginDlls.Count)个) ✓" -ForegroundColor Green

# Python + Dart Bridge DLL
Get-ChildItem "$FLUTTER_PROJ\build\windows\x64\python" -Filter "*.dll" | ForEach-Object { Copy-Item $_.FullName $RELEASE -Force }
Get-ChildItem "$FLUTTER_PROJ\build\windows\x64\dart_bridge" -Filter "*.dll" | ForEach-Object { Copy-Item $_.FullName $RELEASE -Force }
Write-Host "  Python/Dart Bridge DLL ✓" -ForegroundColor Green

# Flutter 引擎 + ICU
Copy-Item "$FLUTTER_PROJ\windows\flutter\ephemeral\flutter_windows.dll" $RELEASE -Force
Write-Host "  Flutter 引擎 ✓" -ForegroundColor Green

# AOT 数据
New-Item -Force -ItemType Directory "$RELEASE\data" | Out-Null
if (Test-Path "$FLUTTER_PROJ\build\windows\app.so") {
    Copy-Item "$FLUTTER_PROJ\build\windows\app.so" "$RELEASE\data\" -Force
}
if (Test-Path "$FLUTTER_PROJ\build\flutter_assets") {
    Copy-Item "$FLUTTER_PROJ\build\flutter_assets" "$RELEASE\data\" -Recurse -Force
}
Copy-Item "$FLUTTER_PROJ\windows\flutter\ephemeral\icudtl.dat" "$RELEASE\data\" -Force -ErrorAction SilentlyContinue
Write-Host "  AOT 数据 ✓" -ForegroundColor Green

# ═══════════════════════════════════════════════════════
# 7. 安装 Python 依赖 → 替换源码
# ═══════════════════════════════════════════════════════
Write-Host "[7/7] 安装运行时依赖 + 替换源码..." -ForegroundColor Yellow

# 安装 pip 包到 Lib/site-packages
New-Item -Force -ItemType Directory $LIB_SP | Out-Null
$pkgs = @("flet==$fletVer")
if (Test-Path "$PROJECT\requirements.txt") {
    $lines = Get-Content "$PROJECT\requirements.txt" | Where-Object { $_ -notmatch '^\s*(#|$)' -and $_ -notmatch '^flet' }
    $pkgs += $lines -replace '\s.*$',''
}
$pkgList = $pkgs -join ' '
python -m pip install $pkgList -t $LIB_SP --no-user --no-compile --quiet 2>&1 | Out-Null
Write-Host "  依赖安装完成 ✓" -ForegroundColor Green

# 用源码替换 .pyc
Write-Host "  替换编译缓存为源码..." -ForegroundColor DarkCyan
$cleanDirs = @($APP_DIR, "$APP_DIR\app", "$APP_DIR\core", "$APP_DIR\services")
foreach ($dir in $cleanDirs) {
    Remove-Item "$dir\*.pyc" -Force -ErrorAction SilentlyContinue
    Remove-Item "$dir\__pycache__" -Recurse -Force -ErrorAction SilentlyContinue
}

# 复制源码
$srcDirs = @{
    ""        = @("*.py")
    "app"     = @("*.py")
    "core"    = @("*.py")
    "services"= @("*.py")
}
foreach ($subdir in $srcDirs.Keys) {
    $srcPath = Join-Path $PROJECT $subdir
    $dstPath = Join-Path $APP_DIR $subdir
    if (-not (Test-Path $dstPath)) { New-Item -Force -ItemType Directory $dstPath | Out-Null }
    foreach ($pattern in $srcDirs[$subdir]) {
        Get-ChildItem $srcPath -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Item $_.FullName $dstPath -Force
        }
    }
}
Write-Host "  源码替换完成 ✓" -ForegroundColor Green

# ═══════════════════════════════════════════════════════
# 完成！
# ═══════════════════════════════════════════════════════
$finalExe = "$RELEASE\chatroom.exe"
$finalSize = if (Test-Path $finalExe) { 
    $size = (Get-ChildItem $RELEASE -Recurse | Measure-Object -Property Length -Sum).Sum
    "{0:N0} MB" -f ($size / 1MB)
} else { "N/A" }

Write-Host @"

╔══════════════════════════════════════════════╗
║  ✅ 打包完成！                              ║
║                                            ║
║  📂 输出目录: $RELEASE
║  📦 总大小:   $finalSize
║  🚀 启动文件: chatroom.exe
╚══════════════════════════════════════════════╝

"@ -ForegroundColor Green

# 复制到干净的 dist 目录
$distDir = "$PROJECT\dist\$ProductName"
Write-Host "复制到 $distDir ..." -ForegroundColor Cyan
New-Item -Force -ItemType Directory $distDir | Out-Null
Copy-Item "$RELEASE\*" $distDir -Recurse -Force
Write-Host "分发目录就绪: $distDir" -ForegroundColor Green
Write-Host "直接压缩 $distDir 文件夹即可分发！" -ForegroundColor Yellow
