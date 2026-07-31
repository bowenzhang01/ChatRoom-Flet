# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · 全局配置与路径常量
  所有模块通过 `import config` 访问配置，使用 `config.API_KEY = xxx` 修改。
  本文件零 UI 框架依赖（Flet 字体注册在 app/theme.py 完成）。
"""

import os
import shutil
import sys as _sys
from pathlib import Path

from utils import load_json

# ═══ 路径常量 ═══
# 打包后(PyInstaller/serious-python)__file__不可靠,
# 用 sys._MEIPASS 定位 bundled 资源
if getattr(_sys, 'frozen', False):
    _bundle_dir = Path(_sys._MEIPASS)
else:
    _bundle_dir = Path(os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = _bundle_dir
PROFILES_DIR = _bundle_dir / "profiles"
ASSETS_DIR = _bundle_dir / "assets"

# ═══ 字体文件路径（供 Flet page.fonts 注册，不再用 Kivy LabelBase）═══
FONT_SC_PATH = ASSETS_DIR / "NotoSansSC-Regular.ttf"
FONT_SC_NAME = "Noto Sans SC"  # Flet 内部引用名

# ═══ 全局 JSON 配置（跨剧本共享的 API / App 设置）═══
# 注意：import 时不向 bundle 目录写入（Android/iOS 打包后 bundle 只读）。
# config.json 的复制/初始化由 path_resolver.setup_workspace() 负责，
# 在打包模式下复制到可写数据目录后再读取。
_config_path = BASE_DIR / "config.json"
if _config_path.exists():
    app_config = load_json(_config_path, default={})
else:
    # bundle 内无 config.json（打包模式首次启动）：先空载，setup_workspace 会重新加载
    app_config = {}


def resolve_key():
    """按优先级解析 API Key：环境变量 > config.json
    环境变量：DEEPSEEK_API_KEY 或 OPENAI_API_KEY"""
    k = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if k:
        return k
    k = app_config.get("model", {}).get("api_key", "")
    if k:
        return k
    return ""


def key_source() -> str:
    """返回 API Key 来源：'env' | 'file' | ''（未配置）"""
    if os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", ""):
        return "env"
    if app_config.get("model", {}).get("api_key", ""):
        return "file"
    return ""


# ═══ 模块级导出（跨文件访问，修改时直接赋值 config.XXX = ...）═══
API_KEY = resolve_key()
MC = app_config.get("model", {})
API_BASE = MC.get("api_base", "https://api.deepseek.com")
MODEL = MC.get("model", "deepseek-chat")
MODELS_LIST = MC.get("models", [])
TEMPERATURE = MC.get("temperature", 0.85)
MAX_TOKENS = MC.get("max_tokens", 300)
ACTIVE_PROFILE = app_config.get("active_profile", "dorm_life")

# ═══ SSL / 代理配置 ═══
# 可在运行时通过设置页修改，修改后立即影响所有新建的 httpx.Client。
# 默认 True（安全）；macOS 企业代理/WSL 代理环境可在设置页关闭。
_network = app_config.get("network", {}) if isinstance(app_config, dict) else {}
API_VERIFY_SSL = _network.get("verify_ssl", True)   # HTTPS 证书校验；自签证书环境需关闭
API_TRUST_ENV = _network.get("trust_env", True)     # 读取系统代理环境变量；WSL/macOS 代理冲突时可关闭

# ═══ 随机事件默认参数（用户不可调，仅作为内置常量）═══
RANDOM_EVENT_DEFAULTS = {
    "min_cooldown": 3,
    "ramp_length": 10,
    "max_probability": 0.35,
    "event_weight": 0.5,
}

# ═══ UI 行为配置 ═══
BEHAVIOR = app_config.get("behavior", {})
STREAMING_ENABLED = BEHAVIOR.get("streaming", True)  # 流式输出，默认开启

# ═══ ComfyUI 配置 ═══
_COMFYUI = app_config.get("comfyui", {})
COMFYUI_HOST = _COMFYUI.get("host", "127.0.0.1")
COMFYUI_PORT = _COMFYUI.get("port", 8188)
COMFYUI_PYTHON_PATH = _COMFYUI.get("python_path", "")
COMFYUI_MAIN_PATH = _COMFYUI.get("comfyui_path", "")
COMFYUI_DATA_PATH = _COMFYUI.get("data_path", "")
COMFYUI_AUTO_START = _COMFYUI.get("auto_start", True)
COMFYUI_AUTO_CLOSE = _COMFYUI.get("auto_close", True)
COMFYUI_STARTUP_TIMEOUT = _COMFYUI.get("startup_timeout", 300)
COMFYUI_GEN_TIMEOUT = _COMFYUI.get("gen_timeout", 600)

# ═══ 图像生成配置 ═══
_IG = app_config.get("image_gen", {})
IMAGE_GEN_ENABLED = _IG.get("enabled", False)
IMAGE_GEN_AUTO_INTERVAL = _IG.get("auto_interval", 6)
IMAGE_GEN_CHAR_COOLDOWN = _IG.get("char_cooldown", 6)
IMAGE_GEN_WIDTH = _IG.get("width", 1024)
IMAGE_GEN_HEIGHT = _IG.get("height", 1024)
IMAGE_GEN_STEPS = _IG.get("steps", 8)
IMAGE_GEN_CFG = _IG.get("cfg", 5.0)

# ═══ ComfyUI 模型配置 ═══
_COMFY_MODELS = app_config.get("models", {})
COMFY_MODEL_DIFFUSION = _COMFY_MODELS.get("diffusion", "flux-2-klein-9b-fp8.safetensors")
COMFY_MODEL_CLIP = _COMFY_MODELS.get("clip", "qwen_3_8b_fp8mixed.safetensors")
COMFY_MODEL_VAE = _COMFY_MODELS.get("vae", "flux2-vae.safetensors")

# ═══ 工作流模板配置 ═══
_WF = app_config.get("workflow", {})
WORKFLOW_PATH = _WF.get("path", "")

# 手动节点 ID 覆盖（兜底用，默认空 = 自动检测 / 内置硬编码）
WORKFLOW_NODE_OVERRIDES = _WF.get("node_overrides", {})
# 格式示例: {"positive_prompt": "12", "sampler": "5", "negative_prompt": "13", ...}


def get_workflow_path():
    if WORKFLOW_PATH and Path(WORKFLOW_PATH).exists():
        return Path(WORKFLOW_PATH)
    return ASSETS_DIR / "simple_api_workflow.json"
