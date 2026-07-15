# -*- coding: utf-8 -*-
"""ChatRoom - Flet Edition · 聊天视图（主界面）
  组合：Header(剧本名·场景▾) + ModeChips + 内容区(空状态/气泡列表)
        + SceneBanner + TransportBar + DirectorInput + StatusBar
  Step 3：骨架 + 空状态 + 模式 Chip + TransportBar + 状态栏
  Step 4：气泡渲染 + EventBus 接入
  Step 5：场景横幅 + 输入栏
"""

import flet as ft

from app.views import ViewBase
from app.theme import RADIUS_PILL, profile_emoji, char_color_at
from app.components.mode_chips import ModeChips
from app.components.transport_bar import TransportBar
from app.components.chat_bubble import make_bubble_row, make_scene_change_row
from app.components.scene_banner import SceneBanner
from app.components.director_input import DirectorInput

__all__ = ["ChatView"]


class ChatView(ViewBase):
    def __init__(self, page, app_state, ui_state, router):
        super().__init__(page, app_state, ui_state, router)
        self._mode_chips: ModeChips = None
        self._transport: TransportBar = None
        self._scene_banner: SceneBanner = None
        self._director_input: DirectorInput = None
        self._title_text: ft.Text = None
        self._scene_text: ft.Text = None
        self._status_dot: ft.Container = None
        self._status_text: ft.Text = None
        self._count_text: ft.Text = None
        self._empty_state: ft.Control = None
        self._content_stack: ft.Stack = None
        self._list_view: ft.ListView = None
        self._built = False
        self._subscribed = False
        self._handlers = {}
        self._near_bottom = True
        self._has_msgs = False
        self._user_turn = False

    # ═══ 构建视图 ═══
    def build(self) -> ft.Control:
        self._mode_chips = ModeChips(self.page, self.state, on_change=self._on_mode_change)
        self._transport = TransportBar(self.page, self.state, on_action=self._on_transport_action)
        self._scene_banner = SceneBanner(self.page)
        self._director_input = DirectorInput(self.page, self.state)

        self._root = ft.Column(
            controls=[
                self._build_header(),
                self._mode_chips.root,
                self._build_content(),
                self._transport.root,
                self._director_input.root,
                self._build_status_bar(),
            ],
            spacing=0,
            expand=True,
        )
        self._built = True
        return self._root

    # ── Header ──
    def _build_header(self) -> ft.Control:
        self._title_text = ft.Text(
            self.state.title, size=18, weight=ft.FontWeight.W_700, max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._scene_text = ft.Text(
            self._scene_label(), size=13, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        title_btn = ft.PopupMenuButton(
            content=ft.Row(
                controls=[
                    self._title_text,
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=2,
            ),
            items=self._build_header_menu_items(),
            on_open=self._refresh_header_menu,
        )
        scene_btn = ft.Container(
            content=ft.Row([self._scene_text], spacing=4),
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            border_radius=RADIUS_PILL,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            on_click=lambda e: self._show_scene_dialog(),
        )

        theme_btn = ft.IconButton(
            icon=ft.Icons.DARK_MODE_OUTLINED,
            selected_icon=ft.Icons.LIGHT_MODE_OUTLINED,
            selected=(self.ui.theme_mode_key == "dark"),
            tooltip="切换主题",
            on_click=self._toggle_theme,
        )
        settings_btn = ft.IconButton(
            icon=ft.Icons.SETTINGS_OUTLINED,
            tooltip="设置",
            on_click=lambda e: self.router.navigate("/settings"),
        )

        return ft.Container(
            content=ft.Row(
                controls=[
                    title_btn,
                    scene_btn,
                    ft.Container(expand=True),
                    theme_btn,
                    settings_btn,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            bgcolor=ft.Colors.SURFACE,
        )

    def _build_header_menu_items(self) -> list:
        items = []
        profiles = self.state.data.get_profile_list()
        if len(profiles) > 1:
            items.append(ft.PopupMenuItem(content=ft.Text("切换剧本"), icon=ft.Icons.MENU_BOOK, on_click=self._go_profiles))
        items.append(ft.PopupMenuItem(content=ft.Text("管理剧本"), icon=ft.Icons.EDIT, on_click=self._go_profiles))
        items.append(ft.PopupMenuItem(content=ft.Divider(height=1), height=1, disabled=True))
        items.append(ft.PopupMenuItem(content=ft.Text("场景设置"), icon=ft.Icons.PLACE_OUTLINED, on_click=lambda e: self._show_scene_dialog()))
        return items

    def _refresh_header_menu(self, e=None):
        if self._title_text:
            self._title_text.value = self.state.title
        if self._scene_text:
            self._scene_text.value = self._scene_label()
        try:
            self.page.update()
        except Exception:
            pass

    # ── 内容区（空状态 + 气泡列表 + banner slot）──
    def _build_content(self) -> ft.Control:
        self._empty_state = self._build_empty_state()
        self._list_view = ft.ListView(
            controls=[],
            expand=True,
            spacing=8,
            padding=ft.Padding.symmetric(horizontal=8, vertical=8),
            auto_scroll=False,
            on_scroll=self._on_scroll,
        )
        self._content_stack = ft.Stack(
            controls=[self._list_view, self._empty_state, self._scene_banner.root],
            expand=True,
        )
        return ft.Container(
            content=self._content_stack,
            expand=True,
            padding=ft.Padding.symmetric(horizontal=0, vertical=0),
        )

    def _bubble_max_width(self) -> float:
        w = self.page.width or 600
        # 减去导航栏宽 + 头像 + 内边距
        if self.ui.is_desktop(self.page):
            w = max(220, w - 72 - 16 - 60)
        else:
            w = max(200, w - 16 - 60)
        return min(w * 0.62, 520)

    def _on_scroll(self, e):
        try:
            pixels = float(getattr(e, "pixels", 0) or 0)
            max_ext = float(getattr(e, "max_scroll_extent", 0) or 0)
            self._near_bottom = (max_ext - pixels) < 120
        except Exception:
            pass

    def _build_empty_state(self) -> ft.Control:
        profiles = self.state.data.get_profile_list()
        folder = profiles[0] if profiles else ""
        emoji = profile_emoji(folder, self.state.title)
        title = ft.Text(self.state.title, size=22, weight=ft.FontWeight.W_700, text_align=ft.TextAlign.CENTER)
        subtitle = ft.Text("对话尚未开始", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        avatars = self._build_character_avatars()
        start_btn = ft.FilledButton(
            content="开始对话",
            icon=ft.Icons.PLAY_ARROW,
            on_click=lambda e: self._on_transport_action("start"),
        )

        col = ft.Column(
            controls=[
                ft.Container(height=24),
                ft.Text(emoji, size=56, text_align=ft.TextAlign.CENTER),
                title,
                subtitle,
                ft.Container(height=8),
                self._characters_divider(),
                avatars,
                ft.Container(height=16),
                start_btn,
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
        )
        return ft.Container(
            content=col,
            alignment=ft.Alignment.CENTER,
            expand=True,
            padding=ft.Padding.all(24),
        )

    def _build_character_avatars(self) -> ft.Control:
        chars = [c for n, c in self.state.characters.items() if n != "You"]
        if not chars:
            return ft.Text("暂无角色", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        total = len(chars)
        avatars = []
        for i, c in enumerate(chars):
            color = char_color_at(i, total)
            dname = c.get("display_name", c.get("name", "?"))
            initial = dname[0] if dname else "?"
            avatars.append(ft.Column(
                controls=[
                    ft.CircleAvatar(
                        content=ft.Text(initial, size=14, color=ft.Colors.WHITE, weight=ft.FontWeight.W_700),
                        bgcolor=color,
                        radius=16,
                    ),
                    ft.Text(dname, size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ))
        return ft.Row(
            controls=avatars,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=16,
            wrap=True,
        )

    def _characters_divider(self) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Container(expand=True, content=ft.Divider(height=1)),
                ft.Text("参与角色", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Container(expand=True, content=ft.Divider(height=1)),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
        )

    # ── 状态栏 ──
    def _build_status_bar(self) -> ft.Control:
        self._status_dot = ft.Container(
            width=8, height=8, border_radius=4,
            bgcolor=ft.Colors.OUTLINE,
        )
        self._status_text = ft.Text("就绪", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self._count_text = ft.Text("0 条", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        to_bottom_btn = ft.IconButton(
            icon=ft.Icons.ARROW_DOWNWARD,
            icon_size=16,
            tooltip="回到底部",
            on_click=lambda e: self._scroll_to_bottom(),
        )
        return ft.Container(
            content=ft.Row(
                controls=[
                    self._status_dot,
                    self._status_text,
                    ft.Container(width=8),
                    self._count_text,
                    ft.Container(expand=True),
                    to_bottom_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=ft.Padding.symmetric(horizontal=16, vertical=6),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        )

    # ═══ 场景/剧本 ═══
    def _scene_label(self) -> str:
        s = self.state.current_scene
        if s and s.get("time"):
            return f"📍 {s.get('time', '')} · {s.get('location', '')}".strip(" ·")
        if self.state.scenes:
            idx = self.state.scene_idx
            if 0 <= idx < len(self.state.scenes):
                sc = self.state.scenes[idx]
            else:
                sc = self.state.scenes[0]
            return f"📍 {sc.get('time', '')} · {sc.get('location', '')}".strip(" ·")
        return "📍 未设置场景"

    def _go_profiles(self, e=None):
        self.router.navigate("/profiles")

    def _show_scene_dialog(self):
        scenes = self.state.scenes or []
        if not scenes:
            return
        controls = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.SCHEDULE),
                title=ft.Text("⏱ 按现实时间生成"),
                on_click=self._make_time_scene_handler(),
            ),
            ft.Divider(height=1),
        ]
        for i, sc in enumerate(scenes):
            controls.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.PLACE_OUTLINED),
                title=ft.Text(f"{sc.get('time', '')} · {sc.get('location', '')}"),
                subtitle=ft.Text(sc.get("mood", ""), size=11),
                on_click=self._make_scene_pick_handler(i),
            ))
        dlg = ft.AlertDialog(
            title=ft.Text("选择场景"),
            content=ft.Column(controls=controls, tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("取消", on_click=lambda e: self._close_dialog())],
        )
        self.page.show_dialog(dlg)

    def _make_time_scene_handler(self):
        def handler(e):
            self.state.scene_idx = -1
            self.state.loop._on_manual_scene_switch()
            self._close_dialog()
            self._refresh_header_menu()
        return handler

    def _make_scene_pick_handler(self, idx):
        def handler(e):
            self.state.scene_idx = idx
            self.state.loop._on_manual_scene_switch()
            self._close_dialog()
            self._refresh_header_menu()
        return handler

    def _close_dialog(self):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    # ═══ 模式 / 传输 ═══
    def _on_mode_change(self, attr, value):
        # 导演/用户模式切换时刷新输入栏可见性
        self._director_input.refresh(
            self.state.director_mode, self.state.user_mode, self._user_turn
        )

    def _on_transport_action(self, action):
        if action == "stop":
            self._confirm_stop()
        elif action == "save":
            try:
                self.state.chat.save_current_chat()
            except Exception as ex:
                print(f"[chat] 保存失败: {ex}")

    def _confirm_stop(self):
        unsaved = self.state.chat.has_unsaved_messages() if hasattr(self.state.chat, "has_unsaved_messages") else False
        count = self.state.message_count

        def do_stop(e=None):
            self.state.loop.stop()
            self._close_dialog()
            self._transport.set_running(False, False)

        dlg = ft.AlertDialog(
            title=ft.Text("停止对话"),
            content=ft.Text(f"当前对话有 {count} 条消息" + ("，部分未保存" if unsaved else "")),
            actions=[
                ft.TextButton("保存并停止", on_click=lambda e: self._save_then_stop(do_stop)),
                ft.FilledButton("直接停止", on_click=do_stop),
                ft.TextButton("取消", on_click=lambda e: self._close_dialog()),
            ],
        )
        self.page.show_dialog(dlg)

    def _save_then_stop(self, after):
        try:
            self.state.chat.save_current_chat()
        except Exception:
            pass
        after()

    # ═══ 主题 ═══
    def _toggle_theme(self, e):
        cur = self.ui.theme_mode_key
        new = "dark" if cur != "dark" else "light"
        self.ui.theme_mode_key = new
        self.ui.save_theme_mode()
        self.page.theme_mode = self.ui.theme_mode()
        e.control.selected = (new == "dark")
        self.page.update()

    # ═══ 滚动 ═══
    def _scroll_to_bottom(self):
        try:
            self._list_view.scroll_to(offset=1_000_000, duration=200)
        except Exception:
            pass

    # ═══ EventBus 订阅 ═══
    def _subscribe(self):
        if self._subscribed:
            return
        bus = self.state.bus
        handlers = {
            "msg": self._on_msg,
            "random_event_msg": self._on_random_event,
            "random_npc_msg": self._on_npc,
            "set_status": self._on_set_status,
            "scene_changed": self._on_scene_changed,
            "user_turn": self._on_user_turn,
            "started": lambda d: self._on_loop_event("started", d),
            "paused": lambda d: self._on_loop_event("paused", d),
            "resumed": lambda d: self._on_loop_event("resumed", d),
            "stopped": lambda d: self._on_loop_event("stopped", d),
            "api_error_stop": self._on_api_error,
            "saving": lambda d: self._on_saving(),
            "saved": self._on_saved,
            "autosave_prompt": self._on_autosave_prompt,
        }
        for ev, h in handlers.items():
            bus.on(ev, h)
            self._handlers[ev] = h
        self._subscribed = True

    def _unsubscribe(self):
        bus = self.state.bus
        for ev, h in self._handlers.items():
            try:
                bus.off(ev, h)
            except Exception:
                pass
        self._handlers.clear()
        self._subscribed = False

    # ── 消息处理 ──
    def _on_msg(self, entry):
        self._add_entry(entry)

    def _on_random_event(self, entry):
        self._add_entry(entry)

    def _on_npc(self, entry):
        self._add_entry(entry)

    def _add_entry(self, entry):
        row = make_bubble_row(entry, self.state, self._bubble_max_width())
        self._add_bubble(row)

    def _add_bubble(self, row: ft.Control):
        # 入场动画：opacity 0→1 + offset 上滑
        row.opacity = 0
        row.offset = ft.Offset(0, 0.04)
        row.animate_opacity = ft.Animation(250, ft.AnimationCurve.EASE_OUT)
        row.animate_offset = ft.Animation(250, ft.AnimationCurve.EASE_OUT)
        self._list_view.controls.append(row)
        # 限制最大条数，避免性能问题
        if len(self._list_view.controls) > 300:
            self._list_view.controls = self._list_view.controls[-300:]
        self._has_msgs = True
        self._empty_state.visible = False
        try:
            self.page.update()
        except Exception:
            pass
        # 触发动画 + 自动滚底
        row.opacity = 1
        row.offset = ft.Offset(0, 0)
        if self._near_bottom:
            self._scroll_to_bottom()
        try:
            self.page.update()
        except Exception:
            pass
        self._update_count()

    def _on_set_status(self, text: str):
        self._update_status(text or "", self.state.running, self.state.paused)

    def _on_scene_changed(self, scene: dict):
        # 场景横幅 + 内联分割行 + 更新 header
        if scene:
            self._scene_banner.show(scene)
            if not scene.get("manual"):
                row = make_scene_change_row(scene, self._bubble_max_width())
                self._add_bubble(row)
        self._refresh_header_menu()

    def _on_user_turn(self, _data):
        self._user_turn = True
        self._update_status("轮到你了～", self.state.running, True)
        self._director_input.refresh(self.state.director_mode, self.state.user_mode, True)

    def _on_loop_event(self, kind, _data):
        if kind == "started":
            self._transport.set_running(True, False)
            self._update_status("运行中", True, False)
        elif kind == "paused":
            self._transport.set_running(True, True)
            self._update_status("已暂停", True, True)
        elif kind == "resumed":
            self._user_turn = False
            self._transport.set_running(True, False)
            self._update_status("运行中", True, False)
            self._director_input.refresh(self.state.director_mode, self.state.user_mode, False)
        elif kind == "stopped":
            self._user_turn = False
            self._transport.set_running(False, False)
            self._update_status("已停止", False, False)
            self._director_input.hide()

    def _on_api_error(self, msg: str):
        self._update_status("API 错误", False, False)
        dlg = ft.AlertDialog(
            title=ft.Text("API 错误"),
            content=ft.Text(msg or "连续失败，对话已停止"),
            actions=[ft.TextButton("知道了", on_click=lambda e: self._close_dialog())],
        )
        try:
            self.page.show_dialog(dlg)
        except Exception:
            pass

    def _on_saving(self):
        self._update_status("正在保存…", self.state.running, self.state.paused)

    def _on_saved(self, data: dict):
        ok = data.get("success", False) if isinstance(data, dict) else False
        msg = data.get("message", "保存成功" if ok else "保存失败") if isinstance(data, dict) else "保存完成"
        # 用状态栏显示保存结果（SnackBar API 在 0.85 不稳定，统一走状态栏）
        self._update_status(msg, self.state.running, self.state.paused)

    def _on_autosave_prompt(self, data: dict):
        title = data.get("title", "未命名") if isinstance(data, dict) else "未命名"
        count = data.get("message_count", 0) if isinstance(data, dict) else 0
        path = data.get("path", "") if isinstance(data, dict) else ""

        def restore(e=None):
            try:
                if path:
                    self.state.chat.restore_autosave(path)
            except Exception as ex:
                print(f"[chat] 恢复自动存档失败: {ex}")
            self._close_dialog()
            self._reload_history_into_list()
            self._refresh_header_menu()

        def discard(e=None):
            try:
                if path:
                    self.state.chat.discard_autosave(path)
            except Exception:
                pass
            self._close_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text("恢复对话"),
            content=ft.Text(f"检测到上次未保存的对话「{title}」{count} 条消息，是否恢复？"),
            actions=[
                ft.FilledButton("恢复", on_click=restore),
                ft.TextButton("放弃", on_click=discard),
            ],
        )
        try:
            self.page.show_dialog(dlg)
        except Exception:
            pass

    def _reload_history_into_list(self):
        """把 state.history 重灌进气泡列表。"""
        self._list_view.controls.clear()
        for entry in self.state.history:
            row = make_bubble_row(entry, self.state, self._bubble_max_width())
            row.opacity = 1
            row.offset = ft.Offset(0, 0)
            self._list_view.controls.append(row)
        self._has_msgs = bool(self.state.history)
        self._empty_state.visible = not self._has_msgs
        try:
            self.page.update()
        except Exception:
            pass
        if self._has_msgs:
            self._scroll_to_bottom()
        self._update_count()

    # ═══ 生命周期 ═══
    def on_enter(self):
        if not self._built:
            return
        self._subscribe()
        self._refresh_header_menu()
        self._mode_chips.refresh()
        self._transport.refresh()
        self._update_status("就绪", self.state.running, self.state.paused)
        self._update_count()
        # 若已有 history（恢复存档后），灌入气泡
        if self.state.history and not self._has_msgs:
            self._reload_history_into_list()

    def on_leave(self):
        self._unsubscribe()

    # ═══ 状态更新（Step 4 EventBus 调用）═══
    def _update_status(self, text: str, running: bool, paused: bool):
        if self._status_text:
            self._status_text.value = text
        if self._status_dot:
            if running and not paused:
                self._status_dot.bgcolor = ft.Colors.TERTIARY  # 青绿 运行
            elif paused:
                self._status_dot.bgcolor = ft.Colors.SECONDARY  # 琥珀 暂停
            else:
                self._status_dot.bgcolor = ft.Colors.OUTLINE
        try:
            self.page.update()
        except Exception:
            pass

    def _update_count(self):
        if self._count_text:
            self._count_text.value = f"{self.state.message_count} 条"
            try:
                self.page.update()
            except Exception:
                pass
