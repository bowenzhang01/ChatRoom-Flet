# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · 平台路径抽象
  统一处理开发模式 / 打包后(Windows/macOS/Linux/Android/iOS/Web)的 writable
  目录与 bundled 资源复制。
  不再依赖 Kivy 的 jnius/PythonActivity；改用平台标准数据目录。
"""

import os
import shutil
import sys
from pathlib import Path

import config
from utils import load_json


def is_packaged() -> bool:
    """当前运行在打包后的可执行文件/APK/iOS 中（非开发模式）。

    PyInstaller 打包: sys.frozen == True, 资源在 sys._MEIPASS
    serious-python(Android/iOS): sys.platform in ("android","ios")
    """
    return getattr(sys, "frozen", False) or sys.platform in ("android", "ios")


def get_data_dir() -> Path:
    """返回 OS 标准应用数据目录。

    • Windows:   %APPDATA%/dorm-flet
    • macOS:     ~/Library/Application Support/dorm-flet
    • Linux:     $XDG_DATA_HOME/dorm-flet 或 ~/.local/share/dorm-flet
    • Android:   ~(沙盒 files_dir 即 /data/data/.../files)
    • iOS:       同上,沙盒内 Path.home()
    """
    plat = sys.platform
    if plat == "win32":
        base = Path(os.environ.get("APPDATA", "") or os.path.expandvars("%USERPROFILE%\\AppData\\Roaming"))
    elif plat == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif plat in ("android", "ios"):
        base = Path.home()
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", "") or Path.home() / ".local" / "share")
    return base / "dorm-flet"


def setup_workspace() -> Path:
    """应用启动时调用。确定 writable 目录，必要时复制 bundled 数据。

    开发模式(is_packaged() == False): 直接用项目目录
    打包后: 首次启动将 bundled profiles + config 复制到数据目录,之后原地读写
    """
    if not is_packaged():
        config.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        return config.PROFILES_DIR

    data_dir = get_data_dir()
    writable_profiles = data_dir / "profiles"
    writable_config = data_dir / "config.json"
    data_dir.mkdir(parents=True, exist_ok=True)

    bundled_config = config.BASE_DIR / "config.json"

    if config.PROFILES_DIR.exists() and not writable_profiles.exists():
        shutil.copytree(str(config.PROFILES_DIR), str(writable_profiles))

    if bundled_config.exists() and not writable_config.exists():
        shutil.copy(str(bundled_config), str(writable_config))

    config.BASE_DIR = data_dir
    config.PROFILES_DIR = writable_profiles
    config.app_config = load_json(writable_config, default={})
    return config.PROFILES_DIR
