# -*- coding: utf-8 -*-
"""
开发调试工具。通过环境变量 DEBUG=dorm 启用详细检查。
所有检查仅输出警告，不抛出异常，不影响生产运行。
用法: DEBUG=dorm python main.py
"""

import os
import threading

_ENABLED = os.environ.get("DEBUG", "").lower() in ("1", "true", "dorm", "all")


def enabled() -> bool:
    return _ENABLED


# ═══ 基础工具 ═══

def trace(msg: str):
    if _ENABLED:
        print(f"[debug] {msg}")


def guard(condition: bool, msg: str):
    """条件检查（仅调试模式下输出警告）。"""
    if _ENABLED and not condition:
        print(f"[debug:guard] {msg}")
        _print_stack(7)


def invariant(condition: bool, msg: str):
    """不变量检查（始终检查，违反时打印严重警告但不崩溃）。"""
    if not condition:
        print(f"[debug:INVARIANT] {msg}")
        if _ENABLED:
            _print_stack(7)


def _print_stack(limit=7):
    import traceback
    for line in traceback.format_stack(limit=limit):
        print(line.rstrip())


# ═══ 线程工具 ═══

def assert_main_thread():
    """确认当前在主线程执行（Flet UI 线程）。"""
    if _ENABLED and threading.current_thread() is not threading.main_thread():
        print("[debug:thread] 警告：在非主线程执行 UI 操作")
        _print_stack(7)


def assert_loop_thread(app):
    """确认当前在 loop 线程执行。"""
    if not _ENABLED:
        return
    loop = getattr(app, 'loop', None)
    if loop and loop._thread:
        if threading.current_thread() is not loop._thread:
            print("[debug:thread] 警告：loop 操作在非 loop 线程执行")
            _print_stack(7)


# ═══ 数据校验 ═══

def validate_profile(app):
    """检查当前加载的剧本数据完整性（load_profile 后调用）。"""
    if not _ENABLED:
        return
    issues = []
    # 检查配置
    if not isinstance(app._profile_config, dict):
        issues.append("_profile_config 不是 dict")
    # 检查角色数据
    if not app.char_dir:
        issues.append("char_dir 未设置")
    elif app.char_dir.exists():
        char_files = list(app.char_dir.glob("*.json"))
        if not char_files:
            issues.append("char_dir 中没有角色文件")
        for entry in app.history:
            name = entry.get("name", "")
            if name and name not in ("__random__", "You") and name not in app.characters:
                issues.append(f"history 引用不存在的角色: {name}")
    # 检查场景
    if app.scene_idx >= 0 and app.scenes:
        if app.scene_idx >= len(app.scenes):
            issues.append(f"scene_idx={app.scene_idx} 越界 scenes[{len(app.scenes)}]")
    # 检查发言顺序
    unknown = [n for n in app.turn_order if n not in app.characters]
    if unknown:
        issues.append(f"turn_order 含不存在的角色: {unknown}")
    # 检查随机事件状态
    if app._active_npc and not isinstance(app._active_npc, dict):
        issues.append(f"_active_npc 类型异常: {type(app._active_npc)}")

    if issues:
        for i in issues:
            print(f"[debug:profile] {i}")
    else:
        trace(f"剧本 {app.profile_dir.name} 数据完整性校验通过")


def validate_runtime_state(app):
    """检查对话运行时状态的一致性（loop 操作前后调用）。"""
    if not _ENABLED:
        return
    issues = []
    if app.running and not app.loop._thread:
        issues.append("running=True 但 loop._thread 为 None")
    if not app.running and app.loop._thread and app.loop._thread.is_alive():
        issues.append("running=False 但 loop 线程仍在运行")
    if app.scene_idx == -1 and not app.scenes and not app.current_scene:
        trace("scene_idx=-1 且无 scenes/current_scene（正常：新剧本）")
    if app._npc_silent_turns < 0:
        issues.append(f"_npc_silent_turns={app._npc_silent_turns} < 0（异常值）")
    if issues:
        for i in issues:
            print(f"[debug:runtime] {i}")


# ═══ EventBus 工具 ═══

def bus_subscription_count(bus):
    """返回各事件的订阅数快照。"""
    counts = {}
    with bus._lock:
        for ev, handlers in bus._subs.items():
            counts[ev] = len(handlers)
    return counts


def check_bus_leaks(bus, expected_event_count: int = 0):
    """检查 bus 是否有未清理的订阅。"""
    if not _ENABLED:
        return
    counts = bus_subscription_count(bus)
    total = sum(counts.values())
    if total > expected_event_count:
        print(f"[debug:bus] 订阅泄漏？当前 {total} 个订阅: {dict(counts)}")
        _print_stack(7)


def trace_bus_sub(bus, event: str, handler, action: str):
    """追踪 EventBus 的 on/off 操作。"""
    if _ENABLED:
        handler_name = getattr(handler, '__name__', str(handler)[:40])
        print(f"[debug:bus] {action} event={event} handler={handler_name}")
