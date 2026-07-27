# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · AI 引擎
  迁移自 Kivy 版 core/ai_engine.py，零 UI 框架依赖。
  - 移除 self.app._set_status / self.app._queue.put（改由 DialogueLoop 通过 EventBus 通知）
  - 移除 self.app._api_error_count 的 UI 联动（错误计数仍保留，停止事件由 loop 发出）
  - 保留：prompt 构建 / 动态发言人选择 / 随机事件 / 路人 NPC 全部逻辑
  - 随机事件参数改用 config.RANDOM_EVENT_DEFAULTS（用户不可调）

  核心方法：
    _build_prompt(name)              → 构建角色 prompt（含场景/历史/输出提示）
    _call_llm(name)                  → 调 LLM 生成角色发言，返回 (text, error_or_None)
    _pick_next_speaker_rules()       → 动态模式加权选人
    _should_trigger_random()         → 随机事件概率判定
    _generate_random_event()         → 生成事件/NPC，返回 dict 或 None
    _generate_npc_response()         → 生成 NPC 回应
    _parse_and_strip_scene_tag(text) → 解析 [SCENE]...[/SCENE] 并返回 (clean_text, scene_or_None)
    _parse_and_strip_next_tag(text)  → 解析 [NEXT:Name] 并返回 (clean_text, next_name_or_None)
"""

import json
import random
import re
from datetime import datetime

from services.api_service import call_chat_completion, call_chat_completion_stream, APIError
from utils import extract_json
import config


class AIEngine:
    """AI 对话引擎 — 通过 app 引用读取状态，不直接操作 UI。"""

    def __init__(self, app):
        self.app = app
        self._api_error_count = 0  # 连续失败计数

    def _stop_check(self) -> bool:
        """供流式 API 检查是否应中断（loop stop 事件触发后立即返回 True）。"""
        return self.app.loop._stop_event.is_set()

    # ═══ 场景与 Prompt 构建 ═══

    def _get_scene_text(self) -> str:
        """构建当前场景文本（供 prompt 使用）。
        优先级：动态 current_scene > 静态 scenes[scene_idx] > 空"""
        if self.app.current_scene and (self.app.dynamic_scene_enabled or self.app.scene_idx == -1):
            s = self.app.current_scene
            src = "dynamic"
        elif self.app.scenes:
            s = self.app.scenes[self.app.scene_idx % len(self.app.scenes)]
            src = "static"
        else:
            s = {"time": "", "scene": "", "location": ""}
            src = "empty"
        loc = f"Location: {s.get('location', '')}. " if s.get('location', '') else ""
        result = f"{s.get('time', '')}. {loc}{s.get('scene', '')}"
        print(f"[scene] prompt source={src}: {result[:80]}...")
        return result

    def _build_prompt(self, name: str) -> str:
        """构建角色发言 prompt。"""
        char = self.app.characters.get(name, {})
        scene = self._get_scene_text()
        recent = self.app.history_snapshot()[-8:] if self.app.history else []
        lines = []
        for m in recent:
            if m.get("type") == "director":
                lines.append(f" (Director's note - incorporate this into the scene): {m['text']}")
            elif m.get("type") == "random_event":
                lines.append(f" (Something happened in the environment): {m['text']}")
            elif m.get("type") == "random_npc":
                npc_name = m.get("display_name", "Stranger")
                lines.append(f"(Passerby {npc_name} says): {m['text']}")
            else:
                dname = m.get("display_name", m["name"])
                lines.append(f"{dname}: {m['text']}")
        dialogue = "\n\n".join(lines) if lines else "(Just arrived)"

        # 用户模式注入提示
        user_note = ""
        if self.app.user_mode and "You" in self.app.characters:
            uc = self.app.characters["You"]
            dname = uc.get('display_name', 'You')
            desc = uc.get('description', 'an ordinary person')
            pers = uc.get('personality', '')
            pers_line = f"Personality: {pers}. " if pers else ""
            user_note = (
                f"\n\n{dname} is also present — {desc}. {pers_line}"
                f"Treat them like any other character. Talk and interact with {dname} naturally."
            )

        return (
            f"{scene}{user_note}\n\n[Recent]\n{dialogue}\n\n"
            f"[Your turn - {char.get('display_name', name)}]\n"
            f"Respond naturally. Describe what you do."
            + self._build_output_hints(name)
        )

    def _build_output_hints(self, current_speaker: str) -> str:
        """动态模式追加 [NEXT] 提示；动态场景追加 [SCENE] 提示。"""
        parts = []

        if self.app.mode == "dynamic":
            others = [n for n in self.app._get_effective_order() if n != current_speaker]
            if others:
                other_names = ", ".join(others)
                parts.append(
                    f"\n\nOn the very last line of your reply ONLY, add [NEXT:Name] "
                    f"to suggest who should speak next. Pick from: {other_names}. "
                    f"Do NOT include [NEXT] inside your dialogue or actions."
                )

        if self.app.dynamic_scene_enabled:
            parts.append(
                f"\n\nIf the physical environment, time, weather, or location has visibly "
                f"changed in your turn, optionally describe the new scene on your very last line:\n"
                f"[SCENE]time. Location: location. description[/SCENE]\n"
                f"Use the same format as the scene description above. "
                f"Only include this if the scene actually changed."
            )

        return "".join(parts)

    # ═══ LLM 调用 ═══

    def _call_llm(self, name: str):
        """调 LLM 生成角色发言。
        返回 (text, error_or_None)。成功时 error 为 None；
        失败时 text 为占位文本，error 为错误消息。
        连续失败 ≥3 次时，error 标记为 'api_error_stop' 触发停止。"""
        char = self.app.characters.get(name)
        if not char:
            return ("...", "Character not found")
        prompt = self._build_prompt(name)
        try:
            content = call_chat_completion(
                messages=[
                    {"role": "system", "content": char["system_prompt"]},
                    {"role": "user", "content": prompt},
                ],
            )
            self._api_error_count = 0
            return (content, None)
        except APIError as e:
            self._api_error_count += 1
            err_msg = str(e)
            print(f"[ai_engine] LLM error ({self._api_error_count}/3): {err_msg}")
            if self._api_error_count >= 3:
                self._api_error_count = 0
                return (f"*{name} ran into trouble*", "api_error_stop:" + err_msg)
            return (f"*{name} is thinking*", err_msg)

    def _call_llm_stream(self, name: str, on_token):
        """Streaming LLM call. Returns (text, error_or_None), same signature as _call_llm.
        Each token is immediately delivered via on_token(token_str)."""
        char = self.app.characters.get(name)
        if not char:
            return ("...", "Character not found")
        prompt = self._build_prompt(name)
        try:
            content = call_chat_completion_stream(
                messages=[
                    {"role": "system", "content": char["system_prompt"]},
                    {"role": "user", "content": prompt},
                ],
                on_token=on_token,
                stop_check=self._stop_check,
            )
            self._api_error_count = 0
            return (content, None)
        except APIError as e:
            self._api_error_count += 1
            err_msg = str(e)
            print(f"[ai_engine] LLM streaming error ({self._api_error_count}/3): {err_msg}")
            if self._api_error_count >= 3:
                self._api_error_count = 0
                return (f"*{name} ran into trouble*", "api_error_stop:" + err_msg)
            return (f"*{name} is thinking*", err_msg)

    # ═══ 动态发言人选择 ═══

    def _pick_next_speaker_rules(self):
        """规则加权随机选人。零 API 成本。
        因子：沉默惩罚 / 直接点名 / 反自说自话 / [NEXT] 提示。
        返回角色 name 或 None（仅 1 人时）。"""
        effective_order = self.app._get_effective_order()
        if not effective_order or len(effective_order) <= 1:
            return None

        # 硬兜底：15 轮沉默强制插入（用户 12 轮）
        HARD_SILENCE = 15
        USER_HARD_SILENCE = 12
        for name in effective_order:
            last = self.app._char_last_turn.get(name, -1)
            silence = self.app.turn_count if last < 0 else self.app.turn_count - last
            limit = USER_HARD_SILENCE if name == "You" else HARD_SILENCE
            if silence >= limit:
                print(f"[director] hard silence: {name} ({silence} turns)")
                return name

        # 上下文
        last_speaker = None
        last_text = ""
        if self.app.history:
            last_msg = self.app.history[-1]
            last_speaker = last_msg.get("name", "")
            last_text = last_msg.get("text", "")

        if self.app._suggested_next:
            print(f"[director] hint from prev char: {self.app._suggested_next}")

        # 计算权重
        weights = {}
        total = 0.0
        for name in effective_order:
            w = 1.0
            factors = []

            # A: 沉默惩罚（用户 0.6× 衰减）
            last = self.app._char_last_turn.get(name, -1)
            silence = self.app.turn_count if last < 0 else self.app.turn_count - last
            sil_bonus = min(silence, 10) * 0.25
            if name == "You":
                sil_bonus *= 0.6
            w += sil_bonus
            if sil_bonus > 0:
                factors.append(f"silence+{sil_bonus:.1f}")

            # B: 直接点名（×3.0）
            if last_text and name in last_text:
                w *= 3.0
                factors.append("mentioned")

            # C: 反自说自话（×0.1）
            if name == last_speaker:
                w *= 0.1
                factors.append("self")

            # D: [NEXT] 提示（×5.0）
            if name == self.app._suggested_next:
                w *= 5.0
                factors.append("hint")

            weights[name] = (w, factors)
            total += w

        if total <= 0:
            picked = random.choice(effective_order)
            print(f"[director] zero weights -> random: {picked}")
            return picked

        # 加权随机
        r = random.random() * total
        cumulative = 0.0
        picked = effective_order[-1]
        for name in effective_order:
            w, factors = weights[name]
            pct = w / total * 100
            factor_str = ", ".join(factors) if factors else "base"
            print(f"[director]   {name}: w={w:.2f} ({pct:.0f}%) [{factor_str}]")
            cumulative += w
            if r <= cumulative:
                picked = name
                break

        print(f"[director] picked: {picked}")
        return picked

    # ═══ 标签解析（[SCENE] / [NEXT]）═══

    def _parse_and_strip_scene_tag(self, text: str):
        """解析并剥离所有 [SCENE]...[/SCENE] 标签。
        返回 (clean_text, scene_dict_or_None)。取最后一个作为有效场景。"""
        scene_matches = list(re.finditer(r'\[SCENE\](.+?)\[/SCENE\]', text, re.DOTALL))
        if not scene_matches:
            return (text, None)
        m = scene_matches[-1]
        scene_content = m.group(1).strip()
        scene_dict = None
        if scene_content:
            scene_dict = self._parse_scene_content(scene_content)
            print(f"[scene] tag detected: {scene_content[:80]}...")
        # 剥离所有 [SCENE] 标签及周围空白（从后向前处理避免偏移）
        clean = text
        for m in reversed(scene_matches):
            start, end = m.start(), m.end()
            while start > 0 and clean[start - 1] in (' ', '\n', '\r', '\t'):
                start -= 1
            while end < len(clean) and clean[end] in (' ', '\n', '\r', '\t'):
                end += 1
            clean = clean[:start] + clean[end:]
        return (clean, scene_dict)

    def _parse_scene_content(self, content: str) -> dict:
        """Parse scene tag content into {time, location, scene} dict.
        Compatible with both English and Chinese punctuation."""
        m = re.match(r'^(.+?)[。.]\s*(?:Location|地点)[：:]\s*(.+?)[。.]\s*(.+)$', content)
        if m:
            return {
                "time": m.group(1).strip(),
                "location": m.group(2).strip(),
                "scene": m.group(3).strip(),
            }
        return {"time": "", "location": "", "scene": content}

    def _parse_and_strip_next_tag(self, text: str):
        """解析并剥离 [NEXT:Name] 标签。
        取最后一个 [NEXT] 建议，剥离所有出现的标签。
        返回 (clean_text, next_name_or_None)。"""
        matches = re.findall(r'\[NEXT:([^\]]+)\]', text)
        if not matches:
            return (text, None)
        next_name = matches[-1].strip()
        clean = re.sub(r'\s*\[NEXT:[^\]]+\]', '', text).strip()
        return (clean, next_name)

    # ═══ 随机事件 / NPC 引擎 ═══

    def _should_trigger_random(self) -> bool:
        """概率斜坡判定是否触发随机事件。参数用 config.RANDOM_EVENT_DEFAULTS。"""
        if not self.app.random_event_enabled:
            return False
        if self.app._active_npc is not None:
            return False
        rc = config.RANDOM_EVENT_DEFAULTS
        min_cooldown = rc["min_cooldown"]
        ramp_length = rc["ramp_length"]
        max_prob = rc["max_probability"]
        turns_since = self.app._char_turns_since_event
        if turns_since < min_cooldown:
            prob = 0.0
        elif turns_since < min_cooldown + ramp_length:
            prob = max_prob * (turns_since - min_cooldown) / ramp_length
        else:
            prob = max_prob
        roll = random.random()
        print(f"[random_event] turns_since={turns_since} p={prob:.3f} roll={roll:.3f} "
              f"trigger={roll < prob}")
        return roll < prob

    def _npc_is_mentioned(self, text: str) -> bool:
        if not self.app._active_npc:
            return False
        npc_name = self.app._active_npc.get("name", "")
        if not npc_name:
            return False
        if npc_name in text:
            print(f"[random_npc] NPC '{npc_name}' mentioned")
            return True
        return False

    def _build_random_event_prompt(self) -> str:
        world_config = self.app._profile_config.get("world", {})
        world_setting = world_config.get("setting", "") if world_config else ""
        world_line = f"[World Setting]\n{world_setting}\n\n" if world_setting else ""
        scene = self._get_scene_text()
        char_names = []
        for name in self.app._get_effective_order():
            st = self.app.char_styles.get(name, {})
            dname = st.get("name", name)
            char_names.append(f"- {dname}")
        char_list = "\n".join(char_names) if char_names else "(No one)"

        event_weight = config.RANDOM_EVENT_DEFAULTS["event_weight"]
        type_hint = "Event" if random.random() < event_weight else "NPC"

        return (
            f"{world_line}"
            f"[Current Scene]\n{scene}\n\n"
            f"[Characters Present]\n{char_list}\n\n"
            f"Please randomly generate a '{type_hint}':\n\n"
            f"If 'Event': Describe an external environmental change or unexpected occurrence (2-4 sentences). "
            f"Only involve the environment/external factors, NOT the specific actions of the characters present.\n"
            f"If 'NPC': Generate a temporary passerby not in the character list above. "
            f"Provide a name (2-4 word common English name), a one-line description, and one line of in-character dialogue (20-40 words).\n\n"
            f"Return pure JSON only, no ``` code blocks:\n"
            f'Event: {{"type":"event","text":"..."}}\n'
            f'NPC: {{"type":"npc","name":"...","desc":"...","dialogue":"..."}}'
        )

    def _build_npc_response_prompt(self, is_intro: bool = False) -> str:
        npc = self.app._active_npc or {}
        npc_name = npc.get("name", "Stranger")
        npc_desc = npc.get("desc", "a passerby")
        scene = self._get_scene_text()
        recent = self.app.history[-6:] if self.app.history else []
        lines = []
        for m in recent:
            dname = m.get("display_name", m["name"])
            if m.get("type") in ("director", "random_event"):
                continue
            lines.append(f"{dname}: {m['text']}")
        dialogue = "\n\n".join(lines) if lines else "(No one spoke)"

        if is_intro:
            return (
                f"{scene}\n\n"
                f"[Recent]\n{dialogue}\n\n"
                f"[Your turn - {npc_name}]\n"
                f"You are a passerby: {npc_desc}. You just walked by and noticed the characters present. "
                f"Say a natural opening line (20-40 words) to join the scene. Wrap dialogue in double quotes \"like this\", use *asterisks* for actions and expressions. "
                f"Don't steal the spotlight — say hello and step aside."
            )
        return (
            f"{scene}\n\n"
            f"[Recent]\n{dialogue}\n\n"
            f"[Your turn - {npc_name}]\n"
            f"You are a passerby: {npc_desc}. "
            f"Respond naturally to the characters' conversation. Keep it short and natural, 50-100 words. Wrap dialogue in double quotes \"like this\", use *asterisks* for actions and expressions. "
            f"Don't steal the spotlight — say your piece and be ready to leave."
        )

    def _generate_random_event(self):
        """生成随机事件/NPC。返回 dict 或 None。"""
        print("[random_event] generating...")
        prompt = self._build_random_event_prompt()
        try:
            content = call_chat_completion(
                messages=[
                    {"role": "system", "content": "You are a scene event/NPC generator. Return JSON only. Events and NPCs should fit the world setting and current scene."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.9,
                max_tokens=300,
            )
            result, err = extract_json(content)
            if result:
                print(f"[random_event] AI returned: type={result.get('type')} "
                      f"text={result.get('text', result.get('dialogue', ''))[:60]}...")
                return result
            print(f"[random_event] JSON parse failed: {err}")
            return None
        except APIError as e:
            print(f"[random_event] API error: {e}")
            return None

    def _generate_npc_response(self):
        """Generate NPC response. Returns text or placeholder."""
        npc = self.app._active_npc or {}
        npc_name = npc.get("name", "Stranger")
        print(f"[random_npc] generating response for '{npc_name}'...")
        prompt = self._build_npc_response_prompt()
        try:
            content = call_chat_completion(
                messages=[
                    {"role": "system", "content": (
                        f"You are playing a temporary passerby character: \"{npc_name}\". "
                        f"{npc.get('desc', 'A pedestrian passing by')}. "
                        f"Respond naturally to the characters present. Keep it short and natural, 50-100 words. Wrap dialogue in double quotes, use *asterisks* for actions and expressions."
                    )},
                    {"role": "user", "content": prompt},
                ],
            )
            print(f"[random_npc] '{npc_name}' response: {content[:80]}...")
            return content
        except APIError as e:
            print(f"[random_npc] API error: {e}")
            return f"*{npc_name} waves a hand*"

    def _generate_npc_response_stream(self, on_token):
        """Streaming generation of NPC response. Returns text or placeholder."""
        npc = self.app._active_npc or {}
        npc_name = npc.get("name", "Stranger")
        print(f"[random_npc] generating streaming response for '{npc_name}'...")
        prompt = self._build_npc_response_prompt()
        try:
            content = call_chat_completion_stream(
                messages=[
                    {"role": "system", "content": (
                        f"You are playing a temporary passerby character: \"{npc_name}\". "
                        f"{npc.get('desc', 'A pedestrian passing by')}. "
                        f"Respond naturally to the characters present. Keep it short and natural, 50-100 words. Wrap dialogue in double quotes, use *asterisks* for actions and expressions."
                    )},
                    {"role": "user", "content": prompt},
                ],
                on_token=on_token,
                stop_check=self._stop_check,
            )
            print(f"[random_npc] '{npc_name}' streaming response: {content[:80]}...")
            return content
        except APIError as e:
            print(f"[random_npc] API streaming error: {e}")
            return f"*{npc_name} waves a hand*"

    def _generate_npc_intro_stream(self, on_token):
        """Streaming generation of NPC intro line. Returns text or placeholder."""
        npc = self.app._active_npc or {}
        npc_name = npc.get("name", "Stranger")
        print(f"[random_npc] generating streaming intro for '{npc_name}'...")
        prompt = self._build_npc_response_prompt(is_intro=True)
        try:
            content = call_chat_completion_stream(
                messages=[
                    {"role": "system", "content": (
                        f"You are playing a temporary passerby character: \"{npc_name}\". "
                        f"{npc.get('desc', 'A pedestrian passing by')}. "
                        f"Say a natural opening line to join the scene. Wrap dialogue in double quotes, use *asterisks* for actions and expressions."
                    )},
                    {"role": "user", "content": prompt},
                ],
                on_token=on_token,
                stop_check=self._stop_check,
            )
            print(f"[random_npc] '{npc_name}' streaming intro: {content[:80]}...")
            return content
        except APIError as e:
            print(f"[random_npc] API streaming intro error: {e}")
            return f"*{npc_name} walks over*"

    # ═══ 时间场景生成（scene_idx == -1 时调用）═══

    def _get_time_label(self) -> str:
        """System hour → English time period label."""
        hour = datetime.now().hour
        if 5 <= hour < 8:
            return "Early Morning"
        elif 8 <= hour < 12:
            return "Morning"
        elif 12 <= hour < 14:
            return "Noon"
        elif 14 <= hour < 17:
            return "Afternoon"
        elif 17 <= hour < 19:
            return "Evening"
        elif 19 <= hour < 22:
            return "Night"
        elif 22 <= hour < 24 or 0 <= hour < 2:
            return "Late Night"
        else:
            return "Dawn"

    def build_time_scene_prompt(self) -> str:
        """构建按现实时间生成场景的 prompt（供 DialogueLoop 在 scene_idx==-1 时调用）。"""
        label = self._get_time_label()
        now = datetime.now()
        wc = self.app._profile_config.get("world", {})
        world_setting = wc.get("setting", "") if wc else ""
        world_line = f"[World Setting]\n{world_setting}\n\n" if world_setting else ""
        return (
            f"{world_line}"
            f"[Current Real Time]\n"
            f"{label} {now.hour:02d}:{now.minute:02d}\n\n"
            f"As a scene designer, create an appropriate scene based on the current real time and world setting.\n\n"
            f"Requirements:\n"
            f"- time: Time label, use \"{label}\" or a similar concise expression, 2-6 words\n"
            f"- location: A specific location name fitting the world setting, 2-6 words\n"
            f"- mood: Atmosphere label, 2-4 words\n"
            f"- scene: Scene description, 80-150 words, like a novel paragraph. Must include at least two sensory details among light, sound, and smell\n\n"
            f"[Output Format] Return pure JSON only, no ``` code blocks:\n"
            f'{{"time":"...","location":"...","mood":"...","scene":"..."}}'
        )

    def generate_time_scene_sync(self):
        """同步调用 LLM 生成时间场景。返回 (scene_dict_or_None, error_or_None)。"""
        prompt = self.build_time_scene_prompt()
        try:
            content = call_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                api_key=config.resolve_key(),
                temperature=0.8,
                max_tokens=500,
            )
            result, err = extract_json(content)
            if result:
                return (result, None)
            return (None, err or "Scene JSON parse failed")
        except APIError as e:
            return (None, str(e))

    # ═══ 对话标题生成（供 ChatManager 调用）═══

    def build_chat_title_prompt(self) -> str:
        """构建对话标题生成 prompt。"""
        recent = self.app.history_snapshot()[-6:] if len(self.app.history) >= 4 else self.app.history_snapshot()
        lines = []
        for m in recent:
            name = m.get("display_name", m.get("name", "?"))
            txt = m.get("text", "")[:80]
            lines.append(f"{name}: {txt}")
        lines_str = "\n".join(lines)
        return (
            f"Based on the following conversation excerpt, generate a short title (5-15 words) summarizing the topic.\n\n"
            f"{lines_str}\n\n"
            f"Return pure JSON: {{\"title\":\"Title\"}}"
        )

    # ═══ AI 一键创建剧本（新版：规划 + 并行展开，真实进度）═══

    def build_planning_prompt(self, description: str) -> str:
        """Phase 1: 生成蓝图规划——返回 world + scene hints + character hints。"""
        return (
            "You are an RPG scenario planner. Based on the user's one-line description, generate a scenario blueprint.\n\n"
            f"User description: {description}\n\n"
            "Return JSON (complete, no omissions):\n"
            "- world: World setting description, 50-150 words\n"
            "- title: Scenario title, 5-15 words\n"
            "- scenes: 4 one-sentence scene hints, each 10-25 words. Scene hints must be distinct from each other\n"
            '- characters: 4-5 character hints (each with name and hint), hint 10-25 words each. Character names must be distinct, do NOT include "You"\n'
            "- you_hint: The You character's role description, 10-25 words\n\n"
            'Return format: {{"world":"...","title":"...","scenes":["...","..."],"characters":[{{"name":"...","hint":"..."}},...],"you_hint":"..."}}\n'
            "Return JSON only, no other text."
        )

    def build_single_scene_prompt(self, hint: str, world: str) -> str:
        """根据一个提示 + 世界观，生成一个完整的场景。"""
        world_line = f"[World Setting]\n{world}\n\n" if world else ""
        return (
            f"{world_line}"
            f"You are a scene designer. Create a complete scene based on the hint.\n\n"
            f"[Scene Hint]\n{hint}\n\n"
            f"Generate the following fields:\n"
            f"- time: Time period name, 2-6 words (e.g., \"Morning\", \"Midnight\")\n"
            f"- location: Location name, 2-6 words\n"
            f"- mood: Atmosphere label, 2-4 words\n"
            f"- scene: Scene description, 80-150 words, like a novel paragraph. Must include at least two sensory details among light, sound, and smell\n\n"
            f"Return pure JSON: {{\"time\":\"...\",\"location\":\"...\",\"mood\":\"...\",\"scene\":\"...\"}}\n"
            f"Return JSON only, no other text."
        )

    def build_single_character_prompt(self, name: str, hint: str, world: str) -> str:
        """Build prompt to generate a complete character from name + hint + world."""
        world_line = f"[World Setting]\n{world}\n\n" if world else ""
        return (
            f"{world_line}"
            f"You are a character designer. Create a complete character based on the hint.\n\n"
            f"[Character Hint]\nName: {name}, Description: {hint}\n\n"
            f"Generate the following fields:\n"
            f"- name: English name, first letter capitalized, 2-5 letters (use the name from the hint, minor adjustments OK)\n"
            f"- display_name: Display name, same as name or a nickname, 1-2 words\n"
            f"- color: Theme color as hex (#RRGGBB format), soft tones based on personality\n"
            f"- bg_color: Background color hex, must be much lighter than color\n"
            f"- personality: Personality tags, 2-4 words\n"
            f"- description: Appearance + identity description, 20-40 words. Include hair color/style, eyes, skin tone, build, etc.\n"
            f"- system_prompt: Complete character persona, following this structure:\n"
            f"  1. Appearance: physical characteristics, clothing\n"
            f"  2. Personality: core traits + expanded description\n"
            f"  3. Speech style: manner of speaking, common expressions\n"
            f"  4. Expression format: Wrap dialogue in double quotes \"like this\", actions in *asterisks*. Give examples\n"
            f"  5. Background: the setting/world, relationships with other characters\n"
            f"  6. Rules: Reply 100-200 words, describe actions and expressions, continue the topic\n"
            f"system_prompt must be a single-line string, use \\\\n for newlines.\n\n"
            f"Use standard English double quotes \" for all dialogue and quoted text. Do NOT use special quotation marks.\n"
            f'Return pure JSON: {{"name":"...","display_name":"...","color":"...","bg_color":"...","personality":"...","description":"...","system_prompt":"..."}}\n'
            f"Return JSON only, no other text."
        )

    def build_you_prompt(self, hint: str, world: str) -> str:
        """Build prompt to generate the You (user avatar) character."""
        world_line = f"[World Setting]\n{world}\n\n" if world else ""
        return (
            f"{world_line}"
            f"You are a character designer. Create a character for the user role (You).\n\n"
            f"[Character Hint]\n{hint}\n\n"
            f"You is the user's avatar in this world — a character with a specific identity, not a spectator. "
            f"Let the user truly feel part of this world through them.\n\n"
            f"Please generate:\n"
            f"- display_name: Display name, default \"You\", can adjust for special identity, 1-2 words\n"
            f"- color: Theme color hex, recommend blue tones like #42a5f5\n"
            f"- bg_color: Background color hex, very light, e.g., #f0f7ff\n"
            f"- personality: Personality tags, 2-4 words\n"
            f"- description: Identity/appearance summary, 15-30 words\n"
            f"- system_prompt: Character persona: role positioning + speech style + expression format (dialogue in double quotes, actions in *asterisks*) + rules (100-200 words)\n"
            f"system_prompt must be single-line, newlines as \\\\n.\n"
            f"Use standard English double quotes \" for all dialogue and quoted text. Do NOT use special quotation marks.\n\n"
            f'Return pure JSON: {{"display_name":"You","color":"#42a5f5","bg_color":"#f0f7ff","personality":"...","description":"...","system_prompt":"..."}}\n'
            f"Return JSON only, no other text."
        )

    def generate_profile_batch_async(self, description: str,
                                       on_plan_ready, on_phase_progress,
                                       on_all_done, on_error):
        """多阶段剧本生成，每阶段提供真实进度回调。

        流程：
            Phase 0 (planning): 1 次 API → blueprint JSON
            Phase 2 (scenes):   顺序分派 N 个场景 API，完一个报一次进度
            Phase 3 (chars):    顺序分派 M 个角色 API，完一个报一次进度
            Phase 4 (writing):  You + 设置 API → on_all_done

        Args:
            description: 用户描述
            on_plan_ready(blueprint): planning 完成时回调，传入蓝图
            on_phase_progress(phase, task_name, phase_done, phase_total, step_idx):
                phase: "scene" | "char" | "writing"
                step_idx: 对应步骤索引 (2=场景, 3=角色, 4=写入)
            on_all_done(results, errors): 全部完成时回调
            on_error(msg): planning 失败时回调
        """
        import threading
        import time as _time
        from services.api_service import call_chat_completion_async

        if not config.API_KEY:
            if on_error:
                on_error("API Key not configured")
            return

        # ── Phase 0: Planning ──
        plan_prompt = self.build_planning_prompt(description)

        def _on_plan_result(content):
            blueprint, err = extract_json(content)
            if not blueprint:
                if on_error:
                    on_error(f"Blueprint parse failed: {err}")
                return
            scenes_hints = blueprint.get("scenes", [])
            chars_hints = blueprint.get("characters", [])
            world = blueprint.get("world", "")
            title = blueprint.get("title", description)
            you_hint = blueprint.get("you_hint", "Yourself")
            if not world:
                world = "A warm and cozy everyday world"
            if not scenes_hints:
                scenes_hints = ["Morning routine", "Afternoon leisure", "Evening stroll", "Late night chat"]
            if len(scenes_hints) < 2:
                scenes_hints = (list(scenes_hints) + ["Afternoon leisure", "Evening stroll", "Late night chat"])[:4]

            world = world.replace('"', '\u201c').replace('"', '\u201d')

            on_plan_ready(blueprint)

            # ── Shared state ──
            results = {
                "world": world,
                "title": title,
                "scenes": [None] * len(scenes_hints),
                "characters": {},
                "you": None,
                "app": {"title": title},
            }
            errors = []
            _lock = threading.Lock()
            STAGGER_MS = 0.35

            # ── Phase runner helper ──
            def _run_phase(tasks, phase_name, step_idx, on_done):
                """Dispatch tasks with stagger. Each completion calls
                on_phase_progress. When all done, calls on_done()."""
                total = len(tasks)
                done_count = [0]
                called = [False]

                def _bump(task_name):
                    with _lock:
                        done_count[0] += 1
                        d = done_count[0]
                        if d >= total and not called[0]:
                            called[0] = True
                            fire = True
                        else:
                            fire = False
                    on_phase_progress(phase_name, task_name, d, total, step_idx)
                    if fire and on_done:
                        on_done()

                _time.sleep(STAGGER_MS)  # small gap between phases
                for i, (prompt, result_cb, mt) in enumerate(tasks):
                    _time.sleep(STAGGER_MS)
                    task_label = f"{phase_name}_{i}"
                    def _wrap(content, rc=result_cb, tn=task_label):
                        rc(content)
                        _bump(tn)
                    call_chat_completion_async(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.85,
                        max_tokens=mt,
                        timeout=45.0,
                        on_result=_wrap,
                        on_error=lambda err, rc=result_cb, tn=task_label: _wrap(""),
                    )

            # ── Build task lists ──

            # Scene tasks
            scene_tasks = []
            for idx, hint in enumerate(scenes_hints):
                def _mk_scene_cb(i):
                    def _cb(content):
                        data, parse_err = extract_json(content)
                        if data and isinstance(data, dict) and data.get("time"):
                            with _lock:
                                results["scenes"][i] = data
                        else:
                            with _lock:
                                errors.append(f"Scene {i + 1}")
                    return _cb
                sp = self.build_single_scene_prompt(hint, world)
                scene_tasks.append((sp, _mk_scene_cb(idx), 800))

            # Character tasks
            char_tasks = []
            for ch in chars_hints:
                cname = ch.get("name", "?")
                ch_hint = ch.get("hint", cname)
                def _mk_char_cb(n):
                    def _cb(content):
                        data, parse_err = extract_json(content)
                        if data and isinstance(data, dict) and data.get("display_name"):
                            with _lock:
                                results["characters"][n] = data
                        else:
                            with _lock:
                                errors.append(f"Character {n}")
                    return _cb
                cp = self.build_single_character_prompt(cname, ch_hint, world)
                char_tasks.append((cp, _mk_char_cb(cname), 1500))

            # Writing tasks (You + App)
            def _cb_you(content):
                data, parse_err = extract_json(content)
                if data and isinstance(data, dict):
                    data["name"] = "You"
                    if not data.get("display_name"):
                        data["display_name"] = "You"
                    with _lock:
                        results["you"] = data
                else:
                    with _lock:
                        results["you"] = {
                            "name": "You", "display_name": "You",
                            "color": "#42a5f5", "bg_color": "#f0f7ff",
                            "personality": "Yourself",
                            "description": "In this world, you are you.",
                            "system_prompt": "You are a participant in this world. Wrap dialogue in double quotes \"like this\", actions in *asterisks*.\nInteract naturally with everyone and respond to others' topics.\nReply concisely, 100-200 words, with vivid detail.",
                        }

            def _cb_app(content):
                data, parse_err = extract_json(content)
                if data and isinstance(data, dict) and data.get("title"):
                    with _lock:
                        results["app"] = {"title": data.get("title", title)}

            yp = self.build_you_prompt(you_hint, world)
            app_prompt_text = (
                f"You are an app settings designer.\n"
                f"[World Setting] {world}\n[Title] {title}\n\n"
                f"Generate an app title (5-15 words)\n"
                f'Return pure JSON: {{"title":"..."}}\n'
                f"Return JSON only."
            )
            writing_tasks = [
                (yp, _cb_you, 1000),
                (app_prompt_text, _cb_app, 400),
            ]

            # ── Sequential phase execution ──
            def _run_all():
                # Phase 2: Scenes
                scene_done = threading.Event()

                def _on_scenes_done():
                    scene_done.set()

                if scene_tasks:
                    _run_phase(scene_tasks, "scene", 2, _on_scenes_done)
                    scene_done.wait()
                else:
                    on_phase_progress("scene", "", 0, 0, 2)

                # Phase 3: Characters
                char_done = threading.Event()

                def _on_chars_done():
                    char_done.set()

                if char_tasks:
                    _run_phase(char_tasks, "char", 3, _on_chars_done)
                    char_done.wait()
                else:
                    on_phase_progress("char", "", 0, 0, 3)

                # Phase 4: Writing
                write_done = threading.Event()

                def _on_write_done():
                    write_done.set()

                _run_phase(writing_tasks, "writing", 4, _on_write_done)
                write_done.wait()

                on_all_done(results, errors)

            threading.Thread(target=_run_all, daemon=True).start()

        call_chat_completion_async(
            messages=[
                {"role": "system", "content": "You are a scenario planner. Return JSON only."},
                {"role": "user", "content": plan_prompt},
            ],
            temperature=0.85,
            max_tokens=1200,
            timeout=45.0,
            on_result=_on_plan_result,
            on_error=lambda err: on_error(str(err)) if on_error else None,
        )

    # ═══ AI 一键创建剧本（旧版：单次调用）═══

    def build_profile_generation_prompt(self, description: str) -> str:
        """构建「一键创建剧本」prompt：从描述生成世界/场景/角色。"""
        return (
            "You are an RPG scenario designer. Based on the user's description, design a ChatRoom role-playing scenario.\n\n"
            f"User description: {description}\n\n"
            "Requirements:\n"
            "1. Generate 3-5 characters with distinct personalities (including name, display_name, personality, appearance description, system_prompt)\n"
            "2. Generate 3-6 scenes (time, location, scene description, mood)\n"
            "3. Provide world setting (1-2 sentences)\n"
            "4. system_prompt should define character persona, speech style, and expression format in detail. Wrap dialogue in double quotes \"like this\", actions in *asterisks*\n"
            "5. Must include a character named \"You\" (display_name: \"You\"), representing the player-controlled character.\n"
            "   Give the user character a personality, appearance, and background fitting this world to provide immersion.\n\n"
            "Return pure JSON with the following structure:\n"
            '{"title":"Scenario Title","world":"World Setting","scenes":['
            '{"time":"Morning","location":"Location","scene":"Description","mood":"Mood"}],'
            '"characters":[{"name":"Yuki","display_name":"Yuki","color":"#7ec8e3",'
            '"description":"Description","personality":"Personality","system_prompt":"Detailed persona"},'
            '{"name":"You","display_name":"You","color":"#42a5f5",'
            '"description":"Description","personality":"Personality","system_prompt":"User character persona"}],'
            '"turn_order":["Yuki","Rui","You"]}\n'
            "Return JSON only, no other text."
        )

    def generate_profile_async(self, description: str, on_result, on_error=None):
        """异步生成完整剧本。on_result(parsed_dict) / on_error(msg)。

        parsed_dict: {title, world, scenes:[...], characters:[...], turn_order:[...]}
        """
        from services.api_service import call_chat_completion_async
        if not config.API_KEY:
            if on_error:
                on_error("API Key not configured")
            return

        prompt = self.build_profile_generation_prompt(description)

        def _on_text(content):
            try:
                data, err = extract_json(content)
                if not data:
                    if on_error:
                        on_error(f"Parse failed: {err}")
                    return
                # Basic validation
                if not data.get("characters") or not data.get("scenes"):
                    if on_error:
                        on_error("Returned data missing characters or scenes")
                    return
                on_result(data)
            except Exception as ex:
                if on_error:
                    on_error(str(ex))

        call_chat_completion_async(
            messages=[
                {"role": "system", "content": "You are a scenario designer. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            on_result=_on_text,
            on_error=on_error,
            temperature=0.9,
            max_tokens=2500,
            timeout=60.0,
        )

    # ═══ AI 生成场景 / 角色 / 推断世界观 / 补全角色 ═══

    def build_generate_scenes_prompt(self) -> str:
        """Build 'AI generate scenes' prompt: generate scene list from world setting and characters."""
        world = self.app._profile_config.get("world", {}).get("setting", "")
        world_line = f"[World Setting]\n{world}\n\n" if world else ""
        char_lines = []
        for name, c in self.app.characters.items():
            dname = c.get("display_name", name)
            desc = c.get("description", "") or c.get("personality", "")
            char_lines.append(f"- {dname}: {desc[:40]}")
        char_list = "\n".join(char_lines) if char_lines else "(No characters yet)"
        existing = self.app.scenes or []
        existing_lines = [f"- {s.get('time','')} - {s.get('location','')}" for s in existing]
        existing_str = "\n".join(existing_lines) if existing_lines else "(None)"

        return (
            f"{world_line}"
            f"[Existing Characters]\n{char_list}\n\n"
            f"[Existing Scenes (avoid duplicates)]\n{existing_str}\n\n"
            f"Please generate 3-6 new scenes for this scenario. Each scene includes:\n"
            f"- time: Time label (2-6 words, e.g., \"Morning\", \"Afternoon\", \"Midnight\")\n"
            f"- location: Location name (2-6 words)\n"
            f"- mood: Atmosphere (2-4 words)\n"
            f"- scene: Scene description (80-150 words, like a novel paragraph, with sensory details)\n\n"
            f"Return pure JSON array, no ``` code blocks:\n"
            f'[{{"time":"...","location":"...","mood":"...","scene":"..."}}]'
        )

    def generate_scenes_async(self, on_result, on_error=None):
        """Async generate scene list. on_result(scenes_list) / on_error(msg)."""
        from services.api_service import call_chat_completion_async
        if not config.API_KEY:
            if on_error:
                on_error("API Key not configured")
            return

        prompt = self.build_generate_scenes_prompt()

        def _on_text(content):
            try:
                data, err = extract_json(content)
                if not data:
                    if on_error:
                        on_error(f"Parse failed: {err}")
                    return
                # Compat: AI may return {"scenes": [...]} instead of bare array
                if isinstance(data, dict):
                    for k in ("scenes", "data", "items", "results"):
                        if isinstance(data.get(k), list):
                            data = data[k]
                            break
                if not isinstance(data, list):
                    if on_error:
                        on_error("Returned data is not a scene list")
                    return
                on_result(data)
            except Exception as ex:
                if on_error:
                    on_error(str(ex))

        call_chat_completion_async(
            messages=[
                {"role": "system", "content": "You are a scene designer. Return JSON array only."},
                {"role": "user", "content": prompt},
            ],
            on_result=_on_text,
            on_error=on_error,
            temperature=0.85,
            max_tokens=1500,
            timeout=45.0,
        )

    def build_generate_characters_prompt(self) -> str:
        """Build 'AI generate characters' prompt: generate character list from world setting and scenes."""
        world = self.app._profile_config.get("world", {}).get("setting", "")
        world_line = f"[World Setting]\n{world}\n\n" if world else ""
        scene_lines = [f"- {s.get('time','')} - {s.get('location','')}: {s.get('scene','')[:40]}"
                       for s in (self.app.scenes or [])]
        scene_list = "\n".join(scene_lines) if scene_lines else "(No scenes yet)"
        existing = [c.get("display_name", name) for name, c in self.app.characters.items()]
        existing_str = ", ".join(existing) if existing else "(None)"

        return (
            f"{world_line}"
            f"[Existing Scenes]\n{scene_list}\n\n"
            f"[Existing Characters (avoid duplicates)]\n{existing_str}\n\n"
            f"Please generate 3-5 new characters for this scenario. Requirements:\n"
            f"1. Name (name: English) and display_name (1-2 words)\n"
            f"2. Distinct personalities — complementary or conflicting\n"
            f"3. color: #RRGGBB format, different hue per character\n"
            f"4. description: Appearance + identity description (30-60 words)\n"
            f"5. personality: Personality keywords (10-20 words)\n"
            f"6. system_prompt: Detailed persona including speech style, expressions, verbal tics, etc.\n"
            f"   Wrap dialogue in double quotes \"like this\", actions in *asterisks*\n\n"
            f"Return pure JSON array, no ``` code blocks:\n"
            f'[{{"name":"Yuki","display_name":"Yuki","color":"#7ec8e3",'
            f'"description":"...","personality":"...","system_prompt":"..."}}]'
        )

    def generate_characters_async(self, on_result, on_error=None):
        """Async generate character list. on_result(characters_list) / on_error(msg)."""
        from services.api_service import call_chat_completion_async
        if not config.API_KEY:
            if on_error:
                on_error("API Key not configured")
            return

        prompt = self.build_generate_characters_prompt()

        def _on_text(content):
            try:
                data, err = extract_json(content)
                if not data:
                    if on_error:
                        on_error(f"Parse failed: {err}")
                    return
                # Compat: AI may return {"characters": [...]} instead of bare array
                if isinstance(data, dict):
                    for k in ("characters", "data", "items", "results"):
                        if isinstance(data.get(k), list):
                            data = data[k]
                            break
                if not isinstance(data, list):
                    if on_error:
                        on_error("Returned data is not a character list")
                    return
                on_result(data)
            except Exception as ex:
                if on_error:
                    on_error(str(ex))

        call_chat_completion_async(
            messages=[
                {"role": "system", "content": "You are a character designer. Return JSON array only."},
                {"role": "user", "content": prompt},
            ],
            on_result=_on_text,
            on_error=on_error,
            temperature=0.9,
            max_tokens=2500,
            timeout=60.0,
        )

    def build_complete_character_prompt(self, char_name: str) -> str:
        """Build 'complete character' prompt: fill in missing fields for an existing character."""
        c = self.app.characters.get(char_name, {})
        world = self.app._profile_config.get("world", {}).get("setting", "")
        world_line = f"[World Setting]\n{world}\n\n" if world else ""
        existing_fields = {k: v for k, v in c.items() if k not in ("bg_color",)}
        fields_str = json.dumps(existing_fields, ensure_ascii=False, indent=2)

        return (
            f"{world_line}"
            f"[Character Existing Info]\n{fields_str}\n\n"
            f"Please complete this character's profile. Keep existing fields, fill in missing ones:\n"
            f"- name: English name (keep if already set)\n"
            f"- display_name: Display name, 1-2 words\n"
            f"- color: #RRGGBB format\n"
            f"- description: Appearance + identity description (30-60 words)\n"
            f"- personality: Personality keywords (10-20 words)\n"
            f"- system_prompt: Detailed persona including speech style, expressions, verbal tics\n"
            f"  Wrap dialogue in double quotes \"like this\", actions in *asterisks*\n\n"
            f"Return pure JSON object, no ``` code blocks"
        )

    def complete_character_async(self, char_name: str, on_result, on_error=None):
        """Async complete character. on_result(completed_char_dict) / on_error(msg)."""
        from services.api_service import call_chat_completion_async
        if not config.API_KEY:
            if on_error:
                on_error("API Key not configured")
            return

        prompt = self.build_complete_character_prompt(char_name)

        def _on_text(content):
            try:
                data, err = extract_json(content)
                if not data:
                    if on_error:
                        on_error(f"Parse failed: {err}")
                    return
                if not isinstance(data, dict):
                    if on_error:
                        on_error("Returned data is not a character object")
                    return
                on_result(data)
            except Exception as ex:
                if on_error:
                    on_error(str(ex))

        call_chat_completion_async(
            messages=[
                {"role": "system", "content": "You are a character designer. Return JSON object only."},
                {"role": "user", "content": prompt},
            ],
            on_result=_on_text,
            on_error=on_error,
            temperature=0.85,
            max_tokens=1200,
            timeout=45.0,
        )

    def build_infer_world_prompt(self) -> str:
        """Build 'infer world setting' prompt: infer world setting from title and scenes."""
        title = self.app.title
        scene_lines = [f"- {s.get('time','')} - {s.get('location','')}: {s.get('scene','')[:60]}"
                       for s in (self.app.scenes or [])]
        scene_list = "\n".join(scene_lines) if scene_lines else "(No scenes)"
        char_lines = [f"- {c.get('display_name', n)}: {c.get('description','')[:40]}"
                      for n, c in self.app.characters.items()]
        char_list = "\n".join(char_lines) if char_lines else "(No characters)"

        return (
            f"[Scenario Title]\n{title}\n\n"
            f"[Existing Scenes]\n{scene_list}\n\n"
            f"[Existing Characters]\n{char_list}\n\n"
            f"Based on the above information, infer and generate a world setting for this scenario.\n"
            f"The world setting should be a 1-3 sentence description summarizing the story's background, era, location, etc.\n\n"
            f"Return pure JSON: {{\"world\":\"World setting description\"}}"
        )

    def infer_world_async(self, on_result, on_error=None):
        """Async infer world setting. on_result(world_str) / on_error(msg)."""
        from services.api_service import call_chat_completion_async
        if not config.API_KEY:
            if on_error:
                on_error("API Key not configured")
            return

        prompt = self.build_infer_world_prompt()

        def _on_text(content):
            try:
                data, err = extract_json(content)
                if not data:
                    if on_error:
                        on_error(f"Parse failed: {err}")
                    return
                world = data.get("world", "")
                if not world:
                    if on_error:
                        on_error("Returned data missing world setting")
                    return
                on_result(world)
            except Exception as ex:
                if on_error:
                    on_error(str(ex))

        call_chat_completion_async(
            messages=[
                {"role": "system", "content": "You are a world setting designer. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            on_result=_on_text,
            on_error=on_error,
            temperature=0.8,
            max_tokens=300,
            timeout=30.0,
        )
