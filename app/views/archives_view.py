# -*- coding: utf-8 -*-
"""ChatRoom - Flet Edition · 对话存档视图
  两级导航：
    1. 剧本列表 — 显示所有剧本及其存档数，点击进入该剧本的存档
    2. 存档列表 — 按日期分组显示该剧本的存档，自动存档置顶
  读取存档时自动切换到该剧本。
"""

from datetime import datetime, timedelta
from pathlib import Path

import flet as ft

import config
from app.views import ViewBase
from app.theme import RADIUS_CARD, TEXT_XL, TEXT_SM, TEXT_ML, TEXT_MD, TEXT_XS
from app.components.profile_card import gather_profile_meta
from app.components.progress_dialog import ProgressDialog

__all__ = ["ArchivesView"]

_PREVIEW_LEN = 60


class ArchivesView(ViewBase):
    def __init__(self, page, app_state, ui_state, router):
        super().__init__(page, app_state, ui_state, router)
        self._header_container: ft.Container = None
        self._search_field: ft.TextField = None
        self._body: ft.Container = None
        self._built = False
        self._save_dialog: ProgressDialog = None
        self._selected_folder: str = None  # None=剧本列表, folder=存档列表
        self._saving = False  # 保存防抖标记
        self._save_completed = False  # 保存是否已成功（防超时线程误覆盖）
        self._save_timed_out = False
        self._save_generation = 0  # 保存代际令牌：隔离旧超时线程，避免干扰新保存

    def build(self) -> ft.Control:
        self._header_container = ft.Container(
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
        )
        self._search_field = ft.TextField(
            hint_text="Search...", dense=True, border_radius=20,
            suffix=ft.Icon(ft.Icons.SEARCH, size=16),
            on_change=lambda e: self._render(),
            on_submit=lambda e: self._render(),
        )
        search_wrap = ft.Container(
            content=self._search_field,
            padding=ft.Padding.symmetric(horizontal=16, vertical=4),
        )
        self._body = ft.Container(expand=True, padding=ft.Padding.all(16))
        self._root = ft.Column(
            controls=[self._header_container, search_wrap, self._body],
            spacing=0,
            expand=True,
        )
        self._built = True
        self._render()
        return self._root

    # ── 渲染 ──
    def _render(self):
        self._refresh_header()
        if self._selected_folder:
            self._body.content = self._build_chats_list(self._selected_folder)
        else:
            self._body.content = self._build_profile_list()
        try:
            self.page.update()
        except Exception:
            pass

    def _refresh_header(self):
        if self._selected_folder:
            meta = gather_profile_meta(self._selected_folder)
            title = meta["title"]
            self._header_container.content = ft.Row(
                controls=[
                    ft.TextButton(
                        content=ft.Text("← Back"),
                        on_click=lambda e: self._back_to_list(),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text("Conversation Archives", size=TEXT_XL, weight=ft.FontWeight.W_700,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(title, size=TEXT_SM, color=ft.Colors.ON_SURFACE_VARIANT,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ],
                        spacing=0, tight=True, expand=True,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            )
        else:
            self._header_container.content = ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text("Conversation Archives", size=TEXT_XL, weight=ft.FontWeight.W_700,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text("Select a profile to view archives", size=TEXT_SM,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ],
                        spacing=0, tight=True, expand=True,
                    ),
                    ft.FilledTonalButton(
                        content=ft.Text("Save Current"), icon=ft.Icons.SAVE,
                        on_click=lambda e: self._save_current(),
                    ),
                    ft.OutlinedButton(
                        content=ft.Text("Copy All"), icon=ft.Icons.CONTENT_COPY,
                        on_click=lambda e: self._copy_all(),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            )

    # ── 第一级：剧本列表 ──
    def _build_profile_list(self) -> ft.Control:
        profiles = self.state.data.get_profile_list()
        active = config.app_config.get("active_profile", "")
        query = (self._search_field.value or "").strip().lower() if self._search_field else ""
        if query:
            profiles = [p for p in profiles if
                        query in p.lower() or
                        query in gather_profile_meta(p)["title"].lower()]
        if not profiles:
            return self._empty_hint("No profiles", "Please create a profile in Profile Library first")
        items = []
        for folder in profiles:
            meta = gather_profile_meta(folder)
            is_active = folder == active
            item = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(
                            ft.Icons.FOLDER if is_active else ft.Icons.FOLDER_OUTLINED,
                            size=24,
                            color=ft.Colors.PRIMARY if is_active else ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(meta["title"], size=TEXT_ML, weight=ft.FontWeight.W_500,
                                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(
                                    f"{meta['chat_count']} archives"
                                    + (" · Current Profile" if is_active else ""),
                                    size=TEXT_SM, color=ft.Colors.ON_SURFACE_VARIANT,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ],
                            spacing=2, tight=True, expand=True,
                        ),
                        ft.Icon(ft.Icons.CHEVRON_RIGHT, size=20,
                                color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                on_click=lambda e, f=folder: self._open_profile(f),
                padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                border_radius=RADIUS_CARD,
                bgcolor=ft.Colors.PRIMARY_CONTAINER if is_active else ft.Colors.SURFACE_CONTAINER_LOW,
            )
            items.append(item)
        return ft.Column(controls=items, spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

    def _open_profile(self, folder: str):
        self._selected_folder = folder
        self._clear_search()
        self._render()

    def _back_to_list(self):
        self._selected_folder = None
        self._clear_search()
        self._render()

    def _clear_search(self):
        if self._search_field:
            self._search_field.value = ""
            try:
                self._search_field.update()
            except Exception:
                pass

    # ── 第二级：存档列表 ──
    def _build_chats_list(self, folder: str) -> ft.Control:
        chats = self.state.chat.list_chats_for_profile(folder)
        query = (self._search_field.value or "").strip().lower() if self._search_field else ""
        if query:
            chats = [(p, m) for p, m in chats if query in m.get("title", "").lower()]
        if not chats:
            return self._empty_hint("No archives", "Start a conversation then tap \"Save Current\" to archive")

        autosaves = [(p, m) for p, m in chats if m.get("is_autosave")]
        normal = [(p, m) for p, m in chats if not m.get("is_autosave")]
        groups = self._group_by_date(normal)

        controls = []
        if autosaves:
            controls.append(self._date_header("Auto-save"))
            for p, m in autosaves:
                controls.append(self._autosave_tile(p, m, folder))
        for label, items in groups:
            controls.append(self._date_header(label))
            for p, m in items:
                controls.append(self._chat_tile(p, m, folder))

        return ft.Column(controls=controls, spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

    def _empty_hint(self, title: str, subtitle: str) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(ft.Icons.FOLDER_OFF_OUTLINED, size=48,
                            color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(title, size=TEXT_MD, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(subtitle, size=TEXT_XS, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
        )

    def _group_by_date(self, items):
        today = datetime.now().date()
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
                label = "Today"
            elif d == yesterday:
                label = "Yesterday"
            elif d is not None:
                label = created[:10]
            else:
                label = "Earlier"
            if label not in groups:
                groups[label] = []
                order.append(label)
            groups[label].append((p, m))
        def _sort_key(l):
            if l == "Today": return (0, "")
            if l == "Yesterday": return (1, "")
            return (2, l)
        order.sort(key=_sort_key, reverse=False)
        dated = [l for l in order if l not in ("Today", "Yesterday")]
        dated.sort(reverse=True)
        final = [l for l in order if l in ("Today", "Yesterday")] + dated
        return [(l, groups[l]) for l in final]

    def _date_header(self, label: str) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Divider(expand=True, height=1),
                ft.Text(label, size=TEXT_XS, color=ft.Colors.ON_SURFACE_VARIANT,
                        weight=ft.FontWeight.W_500),
                ft.Divider(expand=True, height=1),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _chat_tile(self, path, meta, folder) -> ft.Control:
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
                            ft.Text(title, size=TEXT_MD, weight=ft.FontWeight.W_500, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(preview, size=TEXT_XS, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{count} msgs · {created}", size=TEXT_XS,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=2, tight=True, expand=True,
                    ),
                    ft.FilledTonalButton(content=ft.Text("Load"),
                                         on_click=lambda e: self._load(path, folder)),
                    ft.PopupMenuButton(
                        icon=ft.Icons.MORE_VERT,
                        items=[
                            ft.PopupMenuItem(content=ft.Text("Rename"), icon=ft.Icons.EDIT,
                                             on_click=lambda e: self._rename(path, title)),
                            ft.PopupMenuItem(content=ft.Text("Delete"), icon=ft.Icons.DELETE_OUTLINE,
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

    def _autosave_tile(self, path, meta, folder) -> ft.Control:
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
                                    ft.Text("Auto-save", size=TEXT_MD, weight=ft.FontWeight.W_600,
                                            color=ft.Colors.ON_SECONDARY_CONTAINER),
                                    ft.Container(
                                        content=ft.Text("⚡", size=TEXT_XS),
                                        padding=ft.Padding.symmetric(horizontal=4, vertical=1),
                                        border_radius=6,
                                        bgcolor=ft.Colors.SECONDARY_CONTAINER,
                                    ),
                                ],
                                spacing=6,
                            ),
                            ft.Text(preview, size=TEXT_XS, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{count} msgs · Last unsaved", size=TEXT_XS,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=2, tight=True, expand=True,
                    ),
                    ft.FilledTonalButton(content=ft.Text("Load"),
                                         on_click=lambda e: self._load(path, folder)),
                    ft.TextButton(content=ft.Text("Discard"), on_click=lambda e: self._discard(path)),
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
        # 防抖：保存进行中时忽略后续点击
        if self._saving:
            return
        if not self.state.history:
            self._snack("No conversation content to save")
            return
        self._saving = True
        self._save_completed = False
        self._save_timed_out = False
        self._save_generation += 1  # 新保存代际
        my_gen = self._save_generation  # 捕获本次保存的代际令牌
        # 显示保存进度对话框
        self._save_dialog = ProgressDialog(self.page, title="💾 Save Conversation")
        self._save_dialog.show(
            status="Writing conversation data...",
            steps=["Write conversation data", "Generate conversation title", "Complete"],
            indeterminate=True,
        )
        self._save_dialog.set_step(0, "Writing conversation data...")
        # 订阅保存事件
        self.state.bus.on("saving", self._on_saving)
        self.state.bus.on("saved", self._on_saved)
        # 超时兜底：30s 后标记超时，但不覆盖已成功的对话框
        def _save_timeout():
            import time as _t
            _t.sleep(30)
            # 代际校验：若期间用户离开又回来开了新保存，my_gen != 当前代际，本线程放弃操作
            if my_gen != self._save_generation:
                return
            if self._save_completed:
                return
            self._save_timed_out = True
            if self._save_dialog and not self._save_completed:
                self._save_dialog.fail("Save timed out, please retry")
            _t.sleep(30)
            if my_gen != self._save_generation:
                return
            if not self._save_completed:
                self._saving = False
                self._unsubscribe_save_events()
        import threading
        threading.Thread(target=_save_timeout, daemon=True).start()
        try:
            self.state.chat.save_current_chat()
        except Exception as ex:
            if my_gen != self._save_generation:
                return  # 已被新保存取代
            if self._save_dialog:
                self._save_dialog.fail("Save failed: " + str(ex)[:60])
            self._save_dialog = None
            self._saving = False
            self._unsubscribe_save_events()

    def _on_saving(self, _data):
        if self._save_dialog:
            self._save_dialog.set_step(1, "Generating conversation title...", delay=0.1)

    def _on_saved(self, data: dict):
        # 代际校验：若期间用户开了新保存，旧 saved 事件放弃操作（避免覆盖新对话框）
        # 注意：_on_saved 是实例方法，每次保存都订阅同一个方法，无法区分代际；
        # 但新保存会先 unsubscribe 再 subscribe，旧 saved 事件若在新保存之后到达，
        # 会被新保存的 _on_saved 接收——此时用 _save_completed 判断是否已处理过。
        if self._save_completed:
            return  # 本代际已处理过 saved
        ok = data.get("success", False) if isinstance(data, dict) else False
        msg = data.get("message", "Save succeeded" if ok else "Save failed") if isinstance(data, dict) else "Save completed"
        title = data.get("title", "") if isinstance(data, dict) else ""
        self._save_completed = True
        self._saving = False
        if self._save_dialog:
            if ok:
                summary = f"Save succeeded (delayed): {title}" if self._save_timed_out and title else (
                    "Save succeeded (delayed)" if self._save_timed_out else
                    (f"Save succeeded: {title}" if title else "Save succeeded")
                )
                self._save_dialog.set_step(2, "Complete", delay=0.1)
                self._save_dialog.complete(summary, on_close=self._after_save_closed)
            else:
                self._save_dialog.fail(msg)
        else:
            if self._save_timed_out:
                self._snack(f"Save succeeded (delayed): {title}" if title else "Save succeeded (delayed)")
            else:
                self._snack(msg)
        self._unsubscribe_save_events()

    def _unsubscribe_save_events(self):
        try:
            self.state.bus.off("saving", self._on_saving)
            self.state.bus.off("saved", self._on_saved)
        except Exception:
            pass

    def _after_save_closed(self):
        self._save_dialog = None
        self._unsubscribe_save_events()
        # 刷新存档列表
        active = config.app_config.get("active_profile", "")
        if active:
            self._selected_folder = active
        self._render()

    def _load(self, path, folder):
        def _ok(e=None):
            try:
                # 切换到该剧本（停止 loop + 清空 history + 加载剧本）
                if folder != config.app_config.get("active_profile"):
                    self.state.switch_profile(folder)
                elif self.state.loop.running:
                    self.state.loop.stop()
                ok = self.state.chat.load_chat(Path(path))
            except Exception as ex:
                self._close_dialog()
                self._snack("Load failed: " + str(ex)[:60])
                return
            self._close_dialog()
            if ok:
                self._snack("Loaded")
                # chat_view 的 on_leave 已设 _dirty=True，
                # navigate 回 chat 时 on_enter 会自动重灌 history
                self.router.navigate("/chat")
        dlg = ft.AlertDialog(
            title=ft.Text("Load Chat"),
            content=ft.Text("This will overwrite the current conversation and switch profiles. Continue?"),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_dialog()),
                ft.FilledButton("Load", on_click=_ok),
            ],
        )
        self.page.show_dialog(dlg)

    def _discard(self, path):
        def _ok(e=None):
            try:
                self.state.chat.discard_autosave(str(path))
            except Exception:
                pass
            self._close_dialog()
            self._render()
        dlg = ft.AlertDialog(
            title=ft.Text("Discard Auto-save"),
            content=ft.Text("Discard this auto-save? Content will be permanently deleted."),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_dialog()),
                ft.FilledButton("Discard", on_click=_ok),
            ],
        )
        self.page.show_dialog(dlg)

    def _delete(self, path, title):
        def _ok(e=None):
            try:
                self.state.chat.delete_chat(Path(path))
            except Exception:
                pass
            self._close_dialog()
            self._render()
        dlg = ft.AlertDialog(
            title=ft.Text("Delete Archive"),
            content=ft.Text(f"Confirm delete archive \"{title}\"?"),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_dialog()),
                ft.FilledButton("Delete", on_click=_ok),
            ],
        )
        self.page.show_dialog(dlg)

    def _rename(self, path, old_title):
        field = ft.TextField(label="New Title", value=old_title, autofocus=True)
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
            title=ft.Text("Rename Archive"),
            content=field,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_dialog()),
                ft.FilledButton("Save", on_click=_ok),
            ],
        )
        self.page.show_dialog(dlg)

    def _copy_all(self):
        active = config.app_config.get("active_profile", "")
        if self._selected_folder and self._selected_folder != active:
            chats = self.state.chat.list_chats_for_profile(self._selected_folder)
            if not chats:
                self._snack("No chat archives to copy for this profile")
                return
            from utils import load_json
            data = load_json(Path(chats[0][0]))
            hist = data.get("history", []) if data else []
            if not hist:
                self._snack("No conversation content in this archive")
                return
            lines = []
            for entry in hist:
                dname = entry.get("display_name", entry.get("name", "?"))
                t = entry.get("time", "")
                txt = entry.get("text", "")
                lines.append(f"{dname}  {t}\n{txt}")
            text = "\n\n".join(lines)
        else:
            if not self.state.history:
                self._snack("No conversation content to copy")
                return
            lines = []
            for entry in self.state.history:
                dname = entry.get("display_name", entry.get("name", "?"))
                t = entry.get("time", "")
                txt = entry.get("text", "")
                lines.append(f"{dname}  {t}\n{txt}")
            text = "\n\n".join(lines)
        try:
            self.page.clipboard.set(text)
            self._snack("All conversations copied to clipboard")
        except Exception:
            self._snack("Copy failed")

    # ═══ 工具 ═══
    def _close_dialog(self):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def on_enter(self):
        if not self._built:
            return
        self._render()

    def on_leave(self):
        self._unsubscribe_save_events()
        # 关闭挂起的保存对话框，避免跨视图悬挂 + 超时误弹
        if self._save_dialog:
            try:
                self._save_dialog.close()
            except Exception:
                pass
            self._save_dialog = None
        # 关键：置 _save_completed=True 向旧超时线程发"已结束"信号，避免其复活干扰新保存；
        # bump 代际令牌让旧超时线程识别"我已过期"而提前 return。
        # 下次 _save_current 开头会重置为 False + bump 新代际，不影响新流程。
        self._saving = False
        self._save_completed = True
        self._save_generation += 1

    def _safe_render(self):
        if self.page:
            self._render()
