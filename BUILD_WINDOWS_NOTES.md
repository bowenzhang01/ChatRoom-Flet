# Windows 打包踩坑记录

> 2026-07-18 · flet 0.86.0 · Flutter 3.44.4 · Python 3.12

---

## 🕸️ 坑1：GitHub 网络超时

**现象**: `flet build windows` 卡在下载，报 `Timeout was reached` / `信号灯超时`

**原因**: 国内直连 GitHub 极慢，`flet build` 需要下载多个文件

**需要的文件及缓存位置**:

| 文件 | 大小 | 缓存路径 |
|------|------|----------|
| Flutter SDK | ~1GB | `C:\Users\<用户名>\flutter\3.44.4\` |
| Python standalone .tar.gz | 22MB | `~\.flet\cache\python-build-standalone\20260623\` |
| python-windows-for-dart .zip | 21MB | `~\.flet\cache\python-build\v3.12.13-20260714\` |
| dart_bridge DLL (release) | 30KB | `~\.flet\cache\dart-bridge\v1.5.0\` |
| dart_bridge DLL (debug) | 31KB | `~\.flet\cache\dart-bridge\v1.5.0\` |

**解决**: 手动 `Invoke-WebRequest` 下载到缓存目录，或等网络好的时候让它自己下完。

---

## 🔤 坑2：MSVC GBK 编码 → C4819/C2220

**现象**: 
```
error C2220: 以下警告被视为错误
warning C4819: 该文件包含不能在当前代码页(936)中表示的字符
```

**原因**: 中文 Windows 的 MSVC 默认用 GBK(936) 读源码，Flutter 的 `connectivity_plus` 插件源码含非 ASCII 字符。Flutter 模板开了 `/WX`（警告即错误）。

**解决**: 在 `build\flutter\windows\CMakeLists.txt` 的 `project()` 行后加:
```cmake
if(MSVC)
  add_compile_options("/utf-8")
endif()
```

---

## 📦 坑3：CMake install 不完整 — DLL 缺失

**现象**: 编译"成功"但双击 exe 无反应，或提示缺少 `flutter_windows.dll`、`*_plugin.dll`

**原因**: `flutter build windows` 的 CMake install 步骤没有把编译好的插件 DLL 复制到最终输出目录。`flet build windows` 依赖这个步骤。

**缺失的文件清单**:
- `battery_plus_plugin.dll`
- `connectivity_plus_plugin.dll`  
- `pasteboard_plugin.dll`
- `screen_brightness_windows_plugin.dll`
- `screen_retriever_windows_plugin.dll`
- `serious_python_windows_plugin.dll`
- `share_plus_plugin.dll`
- `url_launcher_windows_plugin.dll`
- `window_manager_plugin.dll`
- `flutter_windows.dll` (Flutter 引擎, 20MB)
- `python3.dll` / `python312.dll`
- `dart_bridge.dll` / `dart_bridge_d.dll`
- `vcruntime140.dll` / `vcruntime140_1.dll`

**解决**: 从 `build\flutter\build\windows\x64\plugins\*\Release\` 和 `build\flutter\build\windows\x64\python\` 手动复制到输出目录。

---

## 🗂️ 坑4：AOT 数据缺失

**现象**: `Can't load AOT data from "data\app.so"; no such file`

**原因**: `flutter build windows --release` 需要 AOT 编译 Dart 代码为 `app.so`，但 CMake 问题导致产物没放到正确位置。

**所需文件**:
```
data\
  app.so              ← AOT 编译后的 Dart 代码 (~16MB)
  icudtl.dat           ← ICU 国际化数据
  flutter_assets\      ← Flutter 框架资源
```

**解决**: 从 `build\flutter\build\windows\app.so`、`build\flutter\build\flutter_assets\` 和 `windows\flutter\ephemeral\icudtl.dat` 复制到 `data\`。

---

## 🐍 坑5：site-packages 依赖缺失

**现象**: `ModuleNotFoundError: No module named 'certifi'` → `No module named 'flet'`

**原因**: `flet build windows` 的 Python 打包步骤使用了 `--skip-site-packages --compile-app`。`.pyc` 编译了项目源码但没有 bundler 第三方包（flet、httpx、certifi 等）。`--skip-site-packages` 跳过了全局 pip 包。

**解决**: 
1. 删除 `app/` 下的 `.pyc` 和 `__pycache__/`
2. 用 `.py` 源文件替换（从项目根目录复制）
3. `pip install flet httpx -t Lib\site-packages --no-compile` 把依赖装到 bundled Python 的 site-packages

---

## 🖥️ 坑6：Windows 开发者模式

**现象**: `Building with plugins requires symlink support`

**原因**: Flutter Windows 编译需要符号链接权限

**解决**: 
```powershell
# 管理员 PowerShell
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /v AllowDevelopmentWithoutDevLicense /t REG_DWORD /d 1 /f
```

---

## 🔄 坑7：Python 版本漂移

**现象**: `flet build windows` 默认用 Python 3.14，但本地是 3.12

**原因**: `flet build` 的 `--python-version` 默认值随 flet 版本变化

**解决**: 始终加 `--python-version 3.12`，或设环境变量 `$env:SERIOUS_PYTHON_VERSION = "3.12"`

---

## ✅ 最终可用的流程

见 `build.ps1` 脚本，一个命令搞定以上所有。
