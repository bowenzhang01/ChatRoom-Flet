# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · 蓝白暮光主题 (Soft Twilight · Blue)
  主色重心：正蓝 #4F6FF7
  渐变带：青绿 #10B981 → 蓝 #4F6FF7 → 靛 #6366F1 → 紫 #8B5CF6
    仅用于：剧本封面渐变、角色头像 hue 分配
  强调色：导演琥珀 #F59E0B / 停止玫瑰 #F43F5E / 运行青绿 #10B981
  圆角：卡片/气泡 16、Chip/按钮 pill(全圆)
"""

import flet as ft

__all__ = [
    "build_theme",
    "THEME_MODES",
    "COLORS",
    "GRADIENT_BAND",
    "profile_gradient",
    "char_color_at",
    "PROFILE_EMOJI",
    "profile_emoji",
    "RADIUS_CARD",
    "RADIUS_BUBBLE",
    "RADIUS_PILL",
    "SPACING",
]


# ═══ 主题模式映射 ═══
THEME_MODES = {
    "light": ft.ThemeMode.LIGHT,
    "dark": ft.ThemeMode.DARK,
    "system": ft.ThemeMode.SYSTEM,
}

# ═══ 圆角 / 间距令牌 ═══
RADIUS_CARD = 16
RADIUS_BUBBLE = 16
RADIUS_PILL = 999

SPACING = {  # 4/8/12/16/24/32 网格
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
}

# ═══ 语义色 token（供 UI 控件直接引用，浅/深分开）═══
COLORS = {
    "light": {
        "surface": "#F7F9FF",          # 近白微蓝背景
        "primary": "#4F6FF7",          # 正蓝
        "on_primary": "#FFFFFF",
        "primary_container": "#E0E7FF",  # 用户气泡 / 选中填充
        "on_primary_container": "#1A1F2E",
        "bubble_ai": "#EEF1FE",
        "bubble_ai_text": "#1A1F2E",
        "director": "#FEF3C7",          # 导演气泡
        "director_text": "#3D3520",
        "director_accent": "#F59E0B",
        "success": "#10B981",           # 运行/成功 青绿
        "danger": "#F43F5E",            # 停止/危险 玫瑰
        "text": "#1A1F2E",
        "text_secondary": "#5B6273",
        "text_hint": "#8B92A5",
        "outline": "#C9D0E6",
        "surface_container_low": "#F0F3FC",
        "surface_container_high": "#E7EBF8",
    },
    "dark": {
        "surface": "#0F1420",
        "primary": "#818CF8",          # 提亮
        "on_primary": "#0F1420",
        "primary_container": "#2A2F4A",
        "on_primary_container": "#E6E7F0",
        "bubble_ai": "#1A1F2E",
        "bubble_ai_text": "#E6E7F0",
        "director": "#3D3520",
        "director_text": "#FCE7B0",
        "director_accent": "#F59E0B",
        "success": "#10B981",
        "danger": "#F43F5E",
        "text": "#E6E7F0",
        "text_secondary": "#A0A7BD",
        "text_hint": "#6B7290",
        "outline": "#2A3148",
        "surface_container_low": "#1A1F2E",
        "surface_container_high": "#222840",
    },
}

# ═══ 渐变带（青绿 → 蓝 → 靛 → 紫）═══
GRADIENT_BAND = [
    "#10B981",  # 青绿
    "#22D3EE",  # 青
    "#4F6FF7",  # 正蓝
    "#6366F1",  # 靛
    "#8B5CF6",  # 紫
]


def _hex_to_rgb(hex_str: str) -> tuple:
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _lerp(a, b, t):
    return a + (b - a) * t


def _color_at(t: float) -> str:
    """渐变带上 t∈[0,1] 处的颜色（线性插值）。0=青绿, 1=紫。"""
    t = max(0.0, min(1.0, t))
    n = len(GRADIENT_BAND) - 1
    pos = t * n
    i = int(pos)
    f = pos - i
    if i >= n:
        return GRADIENT_BAND[n]
    c1 = _hex_to_rgb(GRADIENT_BAND[i])
    c2 = _hex_to_rgb(GRADIENT_BAND[i + 1])
    return _rgb_to_hex(tuple(round(_lerp(c1[k], c2[k], f)) for k in range(3)))


def profile_gradient(seed: str, title: str = "") -> ft.LinearGradient:
    """剧本封面渐变：根据关键词取渐变带上的一个区段。

    寝室/日常类取青绿→蓝段，星际/科幻类取蓝→紫段；
    无匹配时按 seed 哈希分配。"""
    text = (seed + title)
    if any(k in text for k in ("寝室", "宿舍", "日常", "校园", "生活", "dorm", "life")):
        start_t, span = 0.0, 0.4       # 青绿→蓝
    elif any(k in text for k in ("星", "飞船", "太空", "科幻", "宇宙", "star", "ship", "space")):
        start_t, span = 0.55, 0.45     # 蓝→紫
    elif any(k in text for k in ("魔法", "奇幻", "magic", "fantasy")):
        start_t, span = 0.35, 0.5      # 青→靛→紫
    elif any(k in text for k in ("武", "江湖", "侠", "sword")):
        start_t, span = 0.0, 0.35      # 偏青绿
    else:
        s = (abs(hash(seed)) % 100) / 100.0 if seed else 0.3
        start_t, span = s * 0.55, 0.4
    end_t = min(1.0, start_t + span)
    return ft.LinearGradient(
        begin=ft.Alignment.TOP_LEFT,
        end=ft.Alignment.BOTTOM_RIGHT,
        colors=[_color_at(start_t), _color_at(end_t)],
    )


def char_color_at(index: int, total: int) -> str:
    """角色头像 hue：沿渐变带均匀分配。"""
    if total <= 1:
        return _color_at(0.55)  # 蓝-靛之间
    t = index / (total - 1)
    # 用渐变带中段 [0.2, 0.8] 分配，避开过青/过紫极端
    return _color_at(0.2 + t * 0.6)


# ═══ 剧本封面 emoji 映射 ═══
PROFILE_EMOJI = {
    "dorm_life": "🏠",
    "starship": "🚀",
}

_PROFILE_KEYWORDS = [
    ("寝室", "🏠"), ("宿舍", "🏠"), ("日常", "🏠"), ("校园", "🎓"),
    ("星", "🚀"), ("飞船", "🚀"), ("太空", "🚀"), ("科幻", "🚀"),
    ("魔法", "🪄"), ("学院", "🎓"), ("武侠", "⚔️"), ("江湖", "⚔️"),
    ("末日", "🏚️"), ("医院", "🏥"), ("公司", "🏢"), ("推理", "🔍"),
]


def profile_emoji(folder_name: str, title: str = "") -> str:
    if folder_name in PROFILE_EMOJI:
        return PROFILE_EMOJI[folder_name]
    text = (folder_name + title)
    for kw, emoji in _PROFILE_KEYWORDS:
        if kw in text:
            return emoji
    return "📖"


_PILL_SHAPE = ft.StadiumBorder()
_CARD_SHAPE = ft.RoundedRectangleBorder(radius=RADIUS_CARD)


def build_theme(mode: str = "light") -> ft.Theme:
    """构建 Flet Theme。

    mode: 'light' | 'dark'
    主色种子正蓝，M3 自动派生 40 色 tonal palette。
    """
    is_dark = mode == "dark"
    c = COLORS[mode]

    # ── 构建完整 ColorScheme（Flet 0.85：color_scheme 默认 None，需显式构造）──
    cs = ft.ColorScheme(
        primary=c["primary"],
        on_primary=c["on_primary"],
        primary_container=c["primary_container"],
        on_primary_container=c["on_primary_container"],
        surface=c["surface"],
        surface_container_low=c["surface_container_low"],
        surface_container_high=c["surface_container_high"],
        outline=c["outline"],
        on_surface=c["text"],
        on_surface_variant=c["text_secondary"],
        secondary=c["director_accent"],
        tertiary=c["success"],
        error=c["danger"],
    )

    theme = ft.Theme(
        color_scheme=cs,
        color_scheme_seed=ft.Colors.BLUE if not is_dark else ft.Colors.INDIGO,
        font_family="Noto Sans SC",
        use_material3=True,
        canvas_color=c["surface"],
        scaffold_bgcolor=c["surface"],
    )

    # ── 组件级圆角（Flet 0.85：组件主题默认 None，需显式赋值实例）──
    theme.card_theme = ft.CardTheme(shape=_CARD_SHAPE)
    theme.chip_theme = ft.ChipTheme(shape=_PILL_SHAPE)
    _pill_style = ft.ButtonStyle(shape=_PILL_SHAPE)
    theme.filled_button_theme = ft.FilledButtonTheme(style=_pill_style)
    theme.outlined_button_theme = ft.OutlinedButtonTheme(style=_pill_style)
    theme.text_button_theme = ft.TextButtonTheme(style=_pill_style)
    theme.button_theme = ft.ButtonTheme(style=_pill_style)
    theme.floating_action_button_theme = ft.FloatingActionButtonTheme(shape=_PILL_SHAPE)

    return theme
