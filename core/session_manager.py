# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · 持久会话管理器

  为每个 AI 角色维护一条持久 transcript。所有 transcript 是**同一份共享对话
  日志的不同视图**：消息定稿时经 append_entry() 扇出到所有角色。

  角色映射规则：
    - 自己的发言       → assistant 身份进入自己的 transcript
    - 其他角色 / You   → user，内容 "显示名: 文本"
    - 导演 / 系统      → user，标签 (导演): / (系统):
    - 随机事件 / 路人  → user，标签 (环境事件): / (路人 xxx):
    - 插画             → user，标签 (插画: ...)
    - 连续同 role 相邻 → 追加合并（仅动尾部，前缀仍命中缓存）

  每轮请求组装（build_messages）：
    [system 角色人设] + [transcript（持久，缓存前缀）] + [临时指令（不入 transcript）]
  - 人设周期重注：每 SESSION_PERSONA_REFRESH 轮在指令前插一条人设 reminder
  - 上下文预算保险丝：超 SESSION_CONTEXT_BUDGET 时异步把最旧部分压成摘要 +
    保留最近 SESSION_KEEP_RAW 条，重建所有 transcript（复用 ai.build_memory_summary_prompt）

  与 stateless 模式共存：通过 config.SESSION_MODE 切换（重启生效）。
  本模块零 UI 依赖，仅通过 app 引用读写状态。
"""

from services.api_service import call_chat_completion_async
import config


class SessionManager:
    def __init__(self, app):
        self.app = app
        self._transcripts = {}  # {role_name: [{"role": ..., "content": ...}, ...]}
        self._compacting = False

    # ═══ 状态 ═══

    @property
    def active(self) -> bool:
        return config.SESSION_MODE == "persistent"

    def _roles(self) -> list:
        return [n for n in self.app._get_effective_order() if n != "You"]

    @property
    def transcripts(self) -> dict:
        return self._transcripts

    # ═══ 生命周期 ═══

    def reset(self):
        """清空所有 transcript（stop / 切换剧本 / 新对话时调用）。"""
        self._transcripts = {r: [] for r in self._roles()}
        self._compacting = False

    def rebuild_from_history(self):
        """从 app.history 重放重建 transcript（load_chat 后调用，确定性回放）。"""
        if not self.active:
            return
        self.reset()
        for entry in self.app.history_snapshot():
            self.append_entry(entry)
        print(f"[session] rebuilt {len(self._transcripts)} sessions "
              f"from {len(self.app.history)} messages")

    # ═══ 扇出 ═══

    def append_entry(self, entry: dict):
        """消息定稿后调用：按角色映射扇出到所有角色 transcript。"""
        if not self.active:
            return
        name = entry.get("name", "")
        text = (entry.get("text") or "").strip()
        if not text:
            return
        etype = entry.get("type", "")
        dname = entry.get("display_name", name)

        for role in list(self._transcripts):
            if name == role:
                msg = {"role": "assistant", "content": text}
            elif etype == "director":
                msg = {"role": "user", "content": f"(导演): {text}"}
            elif etype == "system":
                msg = {"role": "user", "content": f"(系统): {text}"}
            elif etype == "random_event":
                msg = {"role": "user", "content": f"(环境事件): {text}"}
            elif etype == "random_npc":
                msg = {"role": "user", "content": f"(路人 {dname}): {text}"}
            elif etype == "image":
                msg = {"role": "user", "content": f"(插画: {text})"}
            else:
                msg = {"role": "user", "content": f"{dname}: {text}"}
            self._append(role, msg)

    def inject_scene(self, scene: dict):
        """场景状态注入所有 transcript（环境消息）。场景变化 / 会话初始化时调用。"""
        if not self.active or not scene:
            return
        content = f"(当前场景) {scene.get('time', '')}。地点：{scene.get('location', '')}。" \
                  f"{scene.get('scene', '')}".strip()
        self._broadcast_user(content)

    def _broadcast_user(self, content: str):
        if not content:
            return
        for role in list(self._transcripts):
            self._append(role, {"role": "user", "content": content})

    def _append(self, role: str, msg: dict):
        t = self._transcripts.setdefault(role, [])
        if t and t[-1]["role"] == msg["role"]:
            t[-1]["content"] += "\n\n" + msg["content"]
        else:
            t.append(msg)

    # ═══ 请求组装 ═══

    def build_messages(self, name: str) -> list:
        """组装该角色本轮请求的完整 messages 列表。"""
        char = self.app.characters.get(name, {})
        msgs = [{"role": "system", "content": char.get("system_prompt", "")}]
        t = self._transcripts.setdefault(name, [])
        msgs.extend(t)

        # 人设周期重注（依据已完成的自己发言轮数，确定性触发）
        asst_count = sum(1 for m in t if m["role"] == "assistant")
        refresh = config.SESSION_PERSONA_REFRESH
        if refresh > 0 and asst_count > 0 and asst_count % refresh == 0:
            msgs.append({"role": "system", "content": self._build_persona_reminder(char)})

        # 临时指令（不入 transcript → 不破坏缓存前缀）
        msgs.append({"role": "system", "content": self.app.ai._build_turn_instruction(name)})

        # 上下文预算保险丝
        self._maybe_compact(msgs)
        return msgs

    def _build_persona_reminder(self, char: dict) -> str:
        """确定性人设 reminder（内容全部来自角色静态配置）。"""
        name = char.get("name", "")
        dname = char.get("display_name", name)
        pers = char.get("personality", "")
        desc = char.get("description", "")
        lines = ["请务必始终保持以下角色设定，不要脱离人设："]
        if dname:
            lines.append(f"你是「{dname}」")
        if pers:
            lines.append(f"性格：{pers}")
        if desc:
            lines.append(f"身份：{desc}")
        lines.append("保持你的语气风格与表达方式（对话用「」，动作用*星号*）。")
        return "\n".join(lines)

    # ═══ 上下文预算保险丝（1M 上下文下几乎不触发，仅兜底）═══

    def _estimate_tokens(self, msgs: list) -> int:
        total = 0
        for m in msgs:
            total += len(m["content"]) // 2 + 8
        return total

    def _maybe_compact(self, msgs: list):
        budget = config.SESSION_CONTEXT_BUDGET
        if budget <= 0 or self._compacting:
            return
        if self._estimate_tokens(msgs) < budget:
            return
        self._compacting = True
        print(f"[session] transcript 超预算 ({self._estimate_tokens(msgs)} > {budget})，异步压缩中...")

        hist = self.app.history_snapshot()
        keep = config.SESSION_KEEP_RAW
        cutoff = max(len(hist) - keep, 0)
        old = hist[:cutoff]
        if not old:
            self._compacting = False
            return
        lines = []
        for m in old:
            dname = m.get("display_name", m.get("name", "?"))
            txt = (m.get("text") or "").strip()[:100]
            if txt:
                lines.append(f"{dname}: {txt}")
        if not lines:
            self._compacting = False
            return

        prompt = self.app.ai.build_memory_summary_prompt("", "\n".join(lines))
        recent = hist[cutoff:]

        def _on_result(content):
            summary = (content or "").strip()[:600]
            self._apply_compaction(summary, recent)
            self._compacting = False

        def _on_error(err):
            print(f"[session] 压缩失败: {err}")
            self._compacting = False

        call_chat_completion_async(
            messages=[
                {"role": "system", "content": "你是一个对话记忆整理器，只返回摘要文本。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5, max_tokens=400, timeout=30.0,
            on_result=_on_result, on_error=_on_error,
            usage_label="summary",
        )

    def _apply_compaction(self, summary: str, recent: list):
        head = [{"role": "system", "content": f"[记忆摘要]\n{summary}"}]
        for role in list(self._transcripts):
            self._transcripts[role] = list(head)
        for entry in recent:
            self.append_entry(entry)
        print(f"[session] 压缩完成：摘要 {len(summary)} 字 + 保留 {len(recent)} 条原文")
