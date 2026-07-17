# -*- coding: utf-8 -*-
"""ChatRoom - Flet Edition · 聊天气泡（无尾巴卡片）
  按 §2.3 类型对照渲染 5 种气泡：
    - 普通 AI：左对齐，角色色头像，surface_container_low 气泡
    - 用户(You)：右对齐，primary 头像，primary_container 气泡
    - 导演：右对齐，amber 头像，amber_container 气泡 + "导演" tag
    - 随机事件：居中，无头像，"── 🎲 随机事件 ──" 分割线 + 斜体
    - 路人 NPC：左对齐，amber 头像 + "路人" tag，amber 1px 边框；is_farewell 灰显
  气泡 border_radius=16 四角统一，无尾巴。
"""

import flet as ft

from app.theme import RADIUS_BUBBLE, RADIUS_PILL

__all__ = ["make_bubble_row", "make_scene_change_row", "make_random_event_row"]

_TAG_TEXT = {"size": 10, "weight": ft.FontWeight.W_600}


def _tag(text: str, bg: str, color: str) -> ft.Control:
    return ft.Container(
        content=ft.Text(text, **_TAG_TEXT, color=color),
        padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        border_radius=RADIUS_PILL,
        bgcolor=bg,
    )


def _md(text: str, max_width: float) -> ft.Markdown:
    return ft.Markdown(
        value=text or "",
        selectable=True,
        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
        soft_line_break=True,
        shrink_wrap=True,
        fit_content=True,
        width=max_width,
    )


def _bubble(content: ft.Control, bgcolor: str, border=None) -> ft.Container:
    return ft.Container(
        content=content,
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=RADIUS_BUBBLE,
        bgcolor=bgcolor,
        border=border,
    )


def _avatar(initial: str, color: str, radius: int = 16) -> ft.CircleAvatar:
    return ft.CircleAvatar(
        content=ft.Text(initial, size=13, color=ft.Colors.WHITE, weight=ft.FontWeight.W_700),
        bgcolor=color,
        radius=radius,
    )


def make_bubble_row(entry: dict, state, max_width: float) -> ft.Control:
    """根据 entry.type 渲染气泡行。"""
    msg_type = entry.get("type")
    name = entry.get("name", "")
    dname = entry.get("display_name", name)
    text = entry.get("text", "")
    t = entry.get("time", "")

    # ── 随机事件：居中分割线 ──
    if msg_type == "random_event":
        return make_random_event_row(entry, max_width)

    # ── 路人 NPC：左对齐 amber 头像 + "路人" tag ──
    if msg_type == "random_npc":
        return _make_npc_row(entry, max_width)

    # ── 导演：右对齐 amber ──
    if msg_type == "director":
        return _make_director_row(entry, max_width)

    # ── 用户角色 You：右对齐 primary ──
    if name == "You":
        return _make_user_row(entry, max_width)

    # ── 普通 AI：左对齐 ──
    return _make_ai_row(entry, state, max_width)


def _make_ai_row(entry, state, max_width) -> ft.Control:
    name = entry.get("name", "")
    dname = entry.get("display_name", name)
    text = entry.get("text", "")
    t = entry.get("time", "")
    style = state.char_styles.get(name, {}) if state else {}
    if not style:
        for v in state.char_styles.values():
            if v.get("name") == dname:
                style = v
                break
    color = style.get("color") or entry.get("color") or "#888888"
    initial = (dname or name or "?")[0]

    avatar = _avatar(initial, color)
    name_row = ft.Row(
        controls=[
            ft.Text(dname or name, size=12, weight=ft.FontWeight.W_600, color=color),
            ft.Text(t, size=10, color=ft.Colors.ON_SURFACE_VARIANT),
        ],
        spacing=6,
    )
    bubble = _bubble(_md(text, max_width), ft.Colors.SURFACE_CONTAINER_LOW)
    col = ft.Column(controls=[name_row, bubble], tight=True, spacing=4)
    return ft.Row(
        controls=[avatar, col, ft.Container(expand=True)],
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=10,
        tight=False,
    )


def _make_user_row(entry, max_width) -> ft.Control:
    dname = entry.get("display_name", "你")
    text = entry.get("text", "")
    t = entry.get("time", "")
    initial = (dname or "你")[0]

    avatar = _avatar(initial, ft.Colors.PRIMARY)
    name_row = ft.Row(
        controls=[
            ft.Text(t, size=10, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(dname, size=12, weight=ft.FontWeight.W_600, color=ft.Colors.PRIMARY),
        ],
        alignment=ft.MainAxisAlignment.END,
        spacing=6,
    )
    bubble = _bubble(_md(text, max_width), ft.Colors.PRIMARY_CONTAINER)
    col = ft.Column(controls=[name_row, bubble], tight=True, spacing=4)
    return ft.Row(
        controls=[ft.Container(expand=True), col, avatar],
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=10,
        tight=False,
    )


def _make_director_row(entry, max_width) -> ft.Control:
    text = entry.get("text", "")
    t = entry.get("time", "")
    avatar = _avatar("导", ft.Colors.SECONDARY)
    name_row = ft.Row(
        controls=[
            ft.Text(t, size=10, color=ft.Colors.ON_SURFACE_VARIANT),
            _tag("导演", ft.Colors.SECONDARY_CONTAINER, ft.Colors.ON_SECONDARY_CONTAINER),
            ft.Text("导演", size=12, weight=ft.FontWeight.W_600, color=ft.Colors.SECONDARY),
        ],
        alignment=ft.MainAxisAlignment.END,
        spacing=6,
    )
    bubble = _bubble(_md(text, max_width), ft.Colors.SECONDARY_CONTAINER)
    col = ft.Column(controls=[name_row, bubble], tight=True, spacing=4)
    return ft.Row(
        controls=[ft.Container(expand=True), col, avatar],
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=10,
        tight=False,
    )


def _make_npc_row(entry, max_width) -> ft.Control:
    dname = entry.get("display_name", "路人")
    text = entry.get("text", "")
    t = entry.get("time", "")
    is_farewell = entry.get("is_farewell", False)
    initial = (dname or "?")[0]

    avatar = _avatar(initial, ft.Colors.SECONDARY)
    name_row = ft.Row(
        controls=[
            ft.Text(dname, size=12, weight=ft.FontWeight.W_600, color=ft.Colors.SECONDARY),
            _tag("路人", ft.Colors.SECONDARY_CONTAINER, ft.Colors.ON_SECONDARY_CONTAINER),
            ft.Text(t, size=10, color=ft.Colors.ON_SURFACE_VARIANT),
        ],
        spacing=6,
    )
    border = ft.Border.all(1, ft.Colors.SECONDARY)
    bubble = _bubble(_md(text, max_width), ft.Colors.SECONDARY_CONTAINER, border=border)
    col = ft.Column(controls=[name_row, bubble], tight=True, spacing=4)
    row = ft.Row(
        controls=[avatar, col, ft.Container(expand=True)],
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=10,
        tight=False,
    )
    if is_farewell:
        row.opacity = 0.55
    return row


def make_random_event_row(entry, max_width) -> ft.Control:
    text = entry.get("text", "")
    divider_row = ft.Row(
        controls=[
            ft.Divider(expand=True, height=1),
            ft.Text("🎲 随机事件", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Divider(expand=True, height=1),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    body = ft.Text(text, size=13, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
                   text_align=ft.TextAlign.CENTER, width=max_width)
    return ft.Column(
        controls=[divider_row, ft.Container(content=body, alignment=ft.Alignment.CENTER)],
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
        tight=True,
    )


def make_scene_change_row(scene: dict, max_width) -> ft.Control:
    """场景切换内联分割行（Step 5 的 banner 另做）。"""
    label = "📍 场景切换"
    desc = f"{scene.get('time', '')} · {scene.get('location', '')}".strip(" ·")
    divider_row = ft.Row(
        controls=[
            ft.Divider(expand=True, height=1),
            ft.Text(label, size=11, weight=ft.FontWeight.W_600, color=ft.Colors.PRIMARY),
            ft.Divider(expand=True, height=1),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    body = ft.Text(desc, size=12, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
    return ft.Column(
        controls=[divider_row, ft.Container(content=body, alignment=ft.Alignment.CENTER)],
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=4,
        tight=True,
    )
