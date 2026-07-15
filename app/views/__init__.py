# -*- coding: utf-8 -*-
"""ChatRoom - Flet Edition · 视图基类。

所有视图继承 ViewBase，持有 page / state / ui / router 引用。
子类实现 build() 返回根控件，on_enter() 在路由进入时调用。
"""

import flet as ft

__all__ = ["ViewBase"]


class ViewBase:
    """视图基类（非 ft.Control，返回 ft.Control 给 router 装填）。"""

    def __init__(self, page: ft.Page, app_state, ui_state, router):
        self.page = page
        self.state = app_state
        self.ui = ui_state
        self.router = router
        self._root: ft.Control = None

    def build(self) -> ft.Control:
        return ft.Container(
            alignment=ft.Alignment.CENTER,
            content=ft.Text("未实现", size=16),
            expand=True,
        )

    def on_enter(self):
        pass

    def on_leave(self):
        pass
