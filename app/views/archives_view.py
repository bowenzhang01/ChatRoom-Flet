# -*- coding: utf-8 -*-
"""ChatRoom - Flet Edition · 对话存档视图
  AppBar：对话存档 · 剧本名 + [💾 保存当前] + [📋 复制全部]
  按日期分组（今天/昨天/日期）：每条 标题 + 预览 + 消息数 + [读取][⋮]
  自动存档置顶，amber 容器 + ⚡ + "自动存档" tag
"""

from datetime import datetime
from pathlib import Path

import flet as ft

from app.views import ViewBase
from app.theme import RADIUS_CARD

__all__ = ["ArchivesView"]

_PREVIEW_LEN = 60


class ArchivesView(ViewBase):
    def __init__(self, page, app_state, ui_state, router):
        super().__init__(page, app_state, ui_state, router)
        self._body: ft.Container = None
        self._built = False

    def build(self) -> ft.Control:
        self._body = ft.Container(expand=True, padding=ft.Padding.all(16))
        self._root = ft.Column(
            controls=[self._build_header(), self._body],
            spacing=0,
            expand=True,
        )
        self._built = True
        self._render()
        return self._root

    # ── Header ──
    def _build_header(self) -> ft.Control:
        title = self.state.title
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text("对话存档", size=20, weight=ft.FontWeight.W_700),
                            ft.Text(title, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=0, tight=True,
                    ),
                    ft.Container(expand=True),
                    ft.FilledTonalButton(content="保存当前", icon=ft.Icons.SAVE,
                                         on_click=lambda e: self._save_current()),
                    ft.OutlinedButton(content="复制全部", icon=ft.Icons.CONTENT_COPY,
                                      on_click=lambda e: self._copy_all()),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
        )

    # ── 渲染列表 ──
    def _render(self):
        self._body.content = self._build_list()
        try:
            self.page.update()
        except Exception:
            pass

    def _build_list(self) -> ft.Control:
        chats = self.state.chat.list_chats_with_meta()
        if not chats:
            return ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Icon(ft.Icons.FOLDER_OFF_OUTLINED, size=48, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text("暂无存档", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text("开始对话后点击「保存当前」即可存档", size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                alignment=ft.Alignment.CENTER,
                expand=True,
            )

        # 自动存档置顶单独一组
        autosaves = [(p, m) for p, m in chats if m.get("is_autosave")]
        normal = [(p, m) for p, m in chats if not m.get("is_autosave")]
        groups = self._group_by_date(normal)

        controls = []
        if autosaves:
            controls.append(self._date_header("自动存档"))
            for p, m in autosaves:
                controls.append(self._autosave_tile(p, m))
        for label, items in groups:
            controls.append(self._date_header(label))
            for p, m in items:
                controls.append(self._chat_tile(p, m))

        return ft.Column(controls=controls, spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

    def _group_by_date(self, items):
        today = datetime.now().date()
        from datetime import timedelta
        yesterday = today - timedelta(days=1)
        groups = {}
        order = []
        for p, m in items:
            created = m.get("created_at", "")
            try:
                d = datetime.strptime(created[:10], "%Y-%m-%d").date()
            except Exception:
                d = None
            if d == today:
                label = "今天"
            elif d == yesterday:
                label = "昨天"
            elif d is not None:
                label = created[:10]
            else:
                label = "更早"
            if label not in groups:
                groups[label] = []
                order.append(label)
            groups[label].append((p, m))
        # 今天/昨天优先，其余按 label 倒序
        def _sort_key(l):
            if l == "今天": return (0, "")
            if l == "昨天": return (1, "")
            return (2, l)
        order.sort(key=_sort_key, reverse=False)
        # 今天/昨天要排前，其余日期倒序
        dated = [l for l in order if l not in ("今天", "昨天")]
        dated.sort(reverse=True)
        final = [l for l in order if l in ("今天", "昨天")] + dated
        return [(l, groups[l]) for l in final]

    def _date_header(self, label: str) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Divider(expand=True, height=1),
                ft.Text(label, size=11, color=ft.Colors.ON_SURFACE_VARIANT, weight=ft.FontWeight.W_500),
                ft.Divider(expand=True, height=1),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _chat_tile(self, path, meta) -> ft.Control:
        title = meta.get("title", path.stem)
        count = meta.get("message_count", 0)
        created = meta.get("created_at", "")
        preview = self._read_preview(path)
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, size=20, color=ft.Colors.PRIMARY),
                    ft.Column(
                        controls=[
                            ft.Text(title, size=14, weight=ft.FontWeight.W_500, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(preview, size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{count} 条 · {created}", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=2, tight=True, expand=True,
                    ),
                    ft.FilledTonalButton(content="读取", on_click=lambda e: self._load(path)),
                    ft.PopupMenuButton(
                        icon=ft.Icons.MORE_VERT,
                        items=[
                            ft.PopupMenuItem(content=ft.Text("重命名"), icon=ft.Icons.EDIT,
                                             on_click=lambda e: self._rename(path, title)),
                            ft.PopupMenuItem(content=ft.Text("删除"), icon=ft.Icons.DELETE_OUTLINE,
                                             on_click=lambda e: self._delete(path, title)),
                        ],
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=RADIUS_CARD,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )

    def _autosave_tile(self, path, meta) -> ft.Control:
        count = meta.get("message_count", 0)
        preview = self._read_preview(path)
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.BOLT, size=20, color=ft.Colors.SECONDARY),
                    ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text("自动存档", size=14, weight=ft.FontWeight.W_600,
                                            color=ft.Colors.ON_SECONDARY_CONTAINER),
                                    ft.Container(
                                        content=ft.Text("⚡", size=10),
                                        padding=ft.Padding.symmetric(horizontal=4, vertical=1),
                                        border_radius=6,
                                        bgcolor=ft.Colors.SECONDARY_CONTAINER,
                                    ),
                                ],
                                spacing=6,
                            ),
                            ft.Text(preview, size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{count} 条 · 上次未保存", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=2, tight=True, expand=True,
                    ),
                    ft.FilledTonalButton(content="读取", on_click=lambda e: self._load(path)),
                    ft.TextButton(content="放弃", on_click=lambda e: self._discard(path)),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            border_radius=RADIUS_CARD,
            bgcolor=ft.Colors.SECONDARY_CONTAINER,
        )

    def _read_preview(self, path) -> str:
        try:
            from utils import load_json
            data = load_json(Path(path))
            hist = data.get("history", []) if data else []
            if not hist:
                return ""
            first = hist[0]
            txt = first.get("text", "")
            return txt[:_PREVIEW_LEN]
        except Exception:
            return ""

    # ═══ 动作 ═══
    def _save_current(self):
        if not self.state.history:
            self._toast("没有对话内容可保存")
            return
        try:
            self.state.chat.save_current_chat()
            self._toast("正在保存…（AI 生成标题后完成）")
        except Exception as ex:
            self._toast("保存失败：" + str(ex)[:60])
        # 稍后刷新列表（AI 标题生成完成后）
        import threading
        threading.Timer(2.5, self._render).start()

    def _load(self, path):
        def _ok(e=None):
            try:
                ok = self.state.chat.load_chat(Path(path))
            except Exception as ex:
                self._close_dialog()
                self._toast("读取失败：" + str(ex)[:60])
                return
            self._close_dialog()
            if ok:
                self._toast("已读取")
                self.router.navigate("/chat")
                # 通知 chat_view 重灌 history
                chat = self.page.router._get_view("/chat")
                if hasattr(chat, "_reload_history_into_list"):
                    chat._reload_history_into_list()
        dlg = ft.AlertDialog(
            title=ft.Text("读取对话"),
            content=ft.Text("将覆盖当前对话，确定读取？"),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dialog()),
                ft.FilledButton("读取", on_click=_ok),
            ],
        )
        self.page.show_dialog(dlg)

    def _discard(self, path):
        try:
            self.state.chat.discard_autosave(str(path))
        except Exception:
            pass
        self._render()

    def _delete(self, path, title):
        def _ok(e=None):
            try:
                self.state.chat.delete_chat(Path(path))
            except Exception:
                pass
            self._close_dialog()
            self._render()
        dlg = ft.AlertDialog(
            title=ft.Text("删除存档"),
            content=ft.Text(f"确定删除「{title}」？"),
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dialog()),
                ft.FilledButton("删除", on_click=_ok),
            ],
        )
        self.page.show_dialog(dlg)

    def _rename(self, path, old_title):
        field = ft.TextField(label="新标题", value=old_title, autofocus=True)
        def _ok(e=None):
            try:
                from utils import load_json, save_json
                p = Path(path)
                data = load_json(p) or {}
                data["title"] = field.value or old_title
                save_json(p, data)
            except Exception:
                pass
            self._close_dialog()
            self._render()
        dlg = ft.AlertDialog(
            title=ft.Text("重命名存档"),
            content=field,
            actions=[
                ft.TextButton("取消", on_click=lambda e: self._close_dialog()),
                ft.FilledButton("保存", on_click=_ok),
            ],
        )
        self.page.show_dialog(dlg)

    def _copy_all(self):
        lines = []
        for entry in self.state.history:
            dname = entry.get("display_name", entry.get("name", "?"))
            t = entry.get("time", "")
            txt = entry.get("text", "")
            lines.append(f"{dname}  {t}\n{txt}")
        text = "\n\n".join(lines)
        try:
            self.page.clipboard.set(text)
            self._toast("已复制全部对话")
        except Exception:
            self._toast("复制失败")

    # ═══ 工具 ═══
    def _close_dialog(self):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def _toast(self, msg: str):
        dlg = ft.AlertDialog(
            content=ft.Text(msg, size=13),
            actions=[ft.TextButton("好", on_click=lambda e: self._close_dialog())],
        )
        try:
            self.page.show_dialog(dlg)
        except Exception:
            pass

    def on_enter(self):
        if not self._built:
            return
        self._render()
