# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · 纯工具函数（无状态、零 UI 框架依赖）
  load_json / save_json / hex_to_rgba / extract_json
  注：Kivy 版的 make_popup_label 已删除，UI 层用 Flet 控件自行构建。
"""

import json
import re as _re
from pathlib import Path


def load_json(path, default=None):
    """接受 Path 对象或字符串，返回解析后的 JSON。
    文件缺失返回 default，默认 None；调用方应显式传 default。"""
    p = Path(path) if not isinstance(path, Path) else path
    if not p.exists():
        return default
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[load_json] 读取失败 {p}: {e}")
        return default


def save_json(path, data):
    """安全写入 JSON（自动创建父目录）"""
    p = Path(path) if not isinstance(path, Path) else path
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[save_json] 保存失败 {p}: {e}")
        return False


def hex_to_rgba(h, a=1.0):
    """hex 颜色字符串 → (r, g, b, a) 浮点元组。
    保留给可能需要 RGBA 元组的旧逻辑使用；Flet UI 层建议直接用 hex 字符串。"""
    h = h.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
        return (r, g, b, a)
    return (1, 1, 1, a)


def _find_balanced(text: str, start_pos: int):
    """从 start_pos 开始找平衡的括号区间。返回 (start, end) 或 (None, None)。
    正确处理 JSON 字符串内的括号和转义。"""
    open_char = text[start_pos]
    close_char = ']' if open_char == '[' else '}'
    depth = 0
    in_string = False
    escape = False
    for i in range(start_pos, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"' and not in_string:
            in_string = True
        elif c == '"' and in_string:
            in_string = False
        elif not in_string:
            if c == open_char:
                depth += 1
            elif c == close_char:
                depth -= 1
                if depth == 0:
                    return (start_pos, i + 1)
    return (None, None)


def extract_json(text: str):
    """从 AI 返回文本中提取 JSON，处理 markdown 代码块和常见格式错误。

    支持 dict 和 list 两种根类型。
    返回 (dict|list|None, error_msg|None)
    """
    if not text or not text.strip():
        return None, "AI返回为空"
    # Step 0: 移除 DeepSeek R1 等模型的 <think>...</think> 思考标签
    text = _re.sub(r'<think>[\s\S]*?</think>', '', text)
    text = text.strip()
    if not text:
        return None, "AI返回为空（仅含思考标签）"

    # Step 1: 提取 markdown 代码块
    m = _re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, _re.DOTALL)
    if m:
        text = m.group(1).strip()

    # Step 2: 尝试直接解析（最理想情况：纯 JSON）
    result = _try_parse_json(text)
    if result is not None:
        return result, None

    # Step 3: 找最外层结构（平衡括号匹配，处理字符串内括号）
    stripped = text.lstrip()
    if stripped.startswith('['):
        start = text.find('[')
        s, e = _find_balanced(text, start)
        if s is not None:
            candidate = text[s:e]
            result = _try_parse_json(candidate)
            if result is not None:
                return result, None
    elif stripped.startswith('{'):
        start = text.find('{')
        s, e = _find_balanced(text, start)
        if s is not None:
            candidate = text[s:e]
            result = _try_parse_json(candidate)
            if result is not None:
                return result, None
    else:
        bracelet_pos = text.find('{')
        bracket_pos = text.find('[')
        if bracket_pos >= 0 and (bracelet_pos < 0 or bracket_pos < bracelet_pos):
            s, e = _find_balanced(text, bracket_pos)
            if s is not None:
                candidate = text[s:e]
                result = _try_parse_json(candidate)
                if result is not None:
                    return result, None
        if bracelet_pos >= 0:
            s, e = _find_balanced(text, bracelet_pos)
            if s is not None:
                candidate = text[s:e]
                result = _try_parse_json(candidate)
                if result is not None:
                    return result, None

    return None, "JSON解析失败"


def _try_parse_json(text: str):
    """尝试解析 JSON 文本，自动修复常见错误。
    返回 dict/list 或 None（解析失败）。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        fixed = _re.sub(r',\s*([}\]])', r'\1', text)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    try:
        import json5
        return json5.loads(text)
    except Exception:
        pass
    try:
        fixed = _re.sub(r"'(\w+)'\s*:", r'"\1":', text)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    try:
        fixed = _re.sub(r"'([^']*)'", r'"\1"', text)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    return None
