# ChatRoom · Flet Edition 第二轮代码审查错误报告

| 项 | 值 |
|---|---|
| 审查日期 | 2026-07-17 |
| 审查范围 | `config.py` / `utils.py` / `core/*` / `services/*` / `app/**/*` 全部源码（33 个 Python 文件） |
| 审查方法 | 静态通读 + 修复回归分析 + 用户视角操作流程推演 + 线程时序分析 |
| 问题总数 | 23 条 Bug（P0×1, P1×7, P2×8, P3×7） |
| 已修复 | N1, N3（P0×2） |
| 待修复 | N2 + N4 ~ N25（共 23 条） |

---

## 修复状态

| 编号 | 严重度 | 状态 | 修复日期 |
|---|---|---|---|
| N1 | P0 | ✅ 已修复 | 2026-07-17 |
| N3 | P0 | ✅ 已修复 | 2026-07-17 |
| N2 | P0 | ✅ 已修复 | 2026-07-17 |
| N4 ~ N10 | P1 | ⏳ 待修复 | — |
| N11 ~ N18 | P2 | ⏳ 待修复 | — |
| N19 ~ N25 | P3 | ⏳ 待修复 | — |

---

## 审查背景

本次审查针对首轮 BUG_REPORT.md 中 45 条修复完成后的代码，重点检查：
1. 首轮修复是否引入了新的回归 bug
2. 首轮修复是否完整（有无遗漏的边界条件）
3. 修复后的代码是否引入了新的隐藏 bug
4. 用户视角的新操作流程推演

### 首轮修复回归分析

| 首轮编号 | 回归/不完整情况 | 新编号 | 状态 |
|---|---|---|---|
| #22 贪心正则改平衡括号匹配 | 新代码变量名 `brace_pos` 拼写错误（应为 `bracelet_pos`），`NameError` | N1 | ✅ 已修复 |
| #7 `_saving` 超时兜底 | 超时只复位 `_saving`，不关闭 `_save_dialog`，对话框永久悬挂 | N3 | ✅ 已修复 |
| #8 改名迁移 history 引用 | 仅迁移内存 history，未迁移磁盘存档文件；display_name 也改时回退失效 | N5 | ⏳ 待修复 |
| #25 load_profile 重置场景状态 | `load_profile_for_edit` 也调 `data.load_profile`，会 clobber 活跃剧本的场景状态 | N2 | ⏳ 待修复 |
| #37 速度等待改 `_stop_event.wait` | 暂停在高速度下延迟最高 1 秒（旧代码每 0.1s 检查） | N10 | ⏳ 待修复 |

---

## 已修复的 P0 Bug

### N1 `extract_json` 变量名拼写错误 → `NameError` 崩溃 ✅

**定位**：`utils.py:125`

**这是首轮 #22 修复引入的回归。** 首轮将贪心正则改为平衡括号匹配算法，但 `else` 分支中变量名写错：

```python
# 修复前（错误）：
if bracket_pos >= 0 and (brace_pos < 0 or bracket_pos < bracelet_pos):
                               # ^^^^^^^^^^ 未定义！应为 bracelet_pos

# 修复后（正确）：
if bracket_pos >= 0 and (bracelet_pos < 0 or bracket_pos < bracelet_pos):
```

**触发条件**：AI 返回的文本不以 `{` 或 `[` 开头（如 `"Sure! Here are the scenes: [...]"`），且文本中包含 `[`。

**用户感知**：`NameError` 被外层 `except Exception` 吞掉。**AI 生成场景 / AI 生成角色 / AI 生成剧本 / 随机事件生成全部静默失败**。

**修复**：将 `brace_pos` 改为 `bracelet_pos`。

---

### N3 保存超时不关闭进度对话框 → 对话框永久悬挂 ✅

**定位**：`app/views/chat_view.py:452-460`

**这是首轮 #7 修复的不完整实现。** 超时回调只复位 `_saving` 标记，未关闭 `_save_dialog`。

**触发条件**：用户点保存 → AI 标题生成网络挂起（30s+ 无响应）。

**用户感知**：30s 后 `_saving` 复位，状态栏显示"保存超时"。但进度对话框仍显示"正在写入对话数据…"且无关闭按钮。用户无法关闭它。再次点击保存会创建新 `ProgressDialog`，旧对话框引用丢失但仍留在 dialog 栈上。

**修复**：在 `_save_timeout` 中增加关闭对话框的逻辑：
```python
if self._save_dialog:
    self._save_dialog.fail("保存超时，请重试")
    self._save_dialog = None
```

---

## 第一章 · 严重 Bug（P0）⏳ 待修复

### N2 打开活跃剧本的详情页会丢失当前对话的场景状态 ✅

**定位**：
- `app/views/profiles_view.py:701-708`（`_open_detail` 调 `load_profile_for_edit`）
- `core/data_manager.py:144-146`（`load_profile` 无条件重置 `current_scene=None, scene_idx=0`）
- `app/views/chat_view.py:741-752`（`on_enter` 仅在 `current_folder != active` 时恢复场景）

**触发条件**：
1. 用户在剧本 A 的聊天页中对话（`current_scene` 已设）
2. 点导航栏 → 剧本库 → 点 A 的卡片（打开 A 的详情）
3. 点"进入对话"回聊天页

**用户感知**：
步骤 2 中 `load_profile_for_edit(A)` → `data.load_profile(A)` → `current_scene=None, scene_idx=0, scene_version=0`。步骤 3 中 `on_enter` 检查 `current_folder == active` → **跳过**场景恢复逻辑。场景横幅 / header 场景标签变为"未设置场景"或首个静态场景，**正在进行的动态场景上下文丢失**。AI 后续 prompt 基于错误场景生成。

**根因分析**：
`on_enter` 的场景恢复逻辑（saved_scene_idx 等）仅在 `current_folder != active` 时执行。但 `load_profile_for_edit` 对**任何**剧本（包括活跃剧本）都会 clobber 场景状态。当 `folder == active` 时恢复逻辑被跳过。

**修复方向**：
- 方案 A（推荐）：`_open_detail` 中若 `folder == active` 则不调 `load_profile_for_edit`（直接进入详情，数据已在 state 中）
- 方案 B：`on_enter` 无条件保存/恢复场景状态（不论 folder 是否等于 active）
- 方案 C：`load_profile_for_edit` 保存并恢复 `current_scene` 等字段（而非依赖调用方）

**验证建议**：
在 A 剧本对话中开启动态场景 → 场景已切换 → 去剧本库点 A → 回聊天 → 确认场景横幅仍显示之前的动态场景。

**修复**：在 `load_profile_for_edit` 中保存/恢复对话运行时状态（场景上下文 / NPC / 随机事件计数器），因为 `data.load_profile` 会无条件重置它们，而这些是"对话进行中"的状态，不属于剧本配置。

---

## 第二章 · 操作逻辑问题（P1）⏳ 待修复

### N4 设置页行为开关在特定导航路径下静默不持久化

**定位**：`app/views/settings_view.py:284, 290-315`

**触发条件**：
1. 启动 app → 进入设置页（`build()` 时 `pc = self.state._profile_config.setdefault("app", {})` 捕获引用）
2. 去剧本库编辑剧本 B → `load_profile_for_edit(B)` 替换 `_profile_config`
3. 回设置页 → `on_enter`（line 382）检测 `current_folder != active` → `load_profile(active)` 再次替换 `_profile_config`
4. 切换任意行为开关 → `_persist` 写入**旧的** `pc` 引用 → `_save_profile_config` 保存**新的** `_profile_config` → **改动丢失**

**用户感知**：
用户在设置页关闭"随机事件"开关，看到开关已关闭（UI 即时更新），离开设置页。回来发现开关又开了。重启 app 也仍是开。**改动从未写入文件。**

**根因分析**：
`pc` 在 `build()` 时捕获了 `_profile_config["app"]` 的引用。`load_profile` 会替换整个 `_profile_config`（`app_state.py:108` → `data_manager.py:89` `app._profile_config = load_json(...)`）。`on_enter` 的 `load_profile(active)` 再次替换。`_persist` 仍写旧 `pc`，但 `_save_profile_config` 保存新 `_profile_config`。两者指向不同 dict，写入被丢弃。

**修复方向**：
`_persist` 中不使用闭包变量 `pc`，改为实时获取：
```python
def _persist(e=None):
    pc = self.state._profile_config.setdefault("app", {})  # 实时获取
    ...
```

**验证建议**：
编辑剧本 B → 回设置页 → 切换"导演模式"→ 离开设置页 → 回来确认开关状态保持 → 重启 app 确认已持久化。

---

### N5 改名后磁盘存档中的旧角色引用未迁移（#8 修复不完整）

**定位**：
- `app/views/profiles_view.py:432-435, 540-543`（仅迁移 `self.state.history`）
- `app/components/chat_bubble.py:93-98`（display_name 回退）
- `core/chat_manager.py`（无存档迁移逻辑）

**这是首轮 #8 修复的不完整实现。** 首轮修复方向明确说"改名时遍历**所有存档** history"，但实际代码只遍历了当前内存中的 `self.state.history`。

**触发条件**：
1. 剧本有 3 个存档文件，含角色 `Mei`（display_name=`梅芽`）的发言
2. 用 AI 补全把 `Mei` 改名为 ` plum`（display_name=`梅`）
3. 读取旧存档

**用户感知**：
`chat_bubble._make_ai_row` 中 `state.char_styles.get("Mei")` → `{}`（新 char_styles 只有 `plum` 键）。回退逻辑 `for v in state.char_styles.values(): if v.get("name") == dname` — `dname` 是存档 entry 中的 `display_name="梅芽"`，但新 char_styles 的 `name` 是 `"梅"`。不匹配。头像变灰（`#888888`），角色名虽保留但颜色丢失。

**根因分析**：
存档文件中的 `entry["name"]` 和 `entry["display_name"]` 均未迁移。`chat_bubble` 回退依赖 display_name 匹配，但改名后 display_name 也变了。

**修复方向**：
- 改名时遍历该剧本 `chats/` 目录下所有 `chat_*.json` 和 `_autosave.json`，更新 `entry["name"]` 和 `entry["display_name"]`
- 或在角色数据中保留 `aliases: [old_name, ...]` 字段，渲染时按 alias 回退

**验证建议**：
改名后读取 3 个旧存档，确认所有气泡头像颜色与显示名正确。

---

### N6 `_reload_history_into_list` 迭代 deque 未加锁

**定位**：`app/views/chat_view.py:717-733`

```python
def _reload_history_into_list(self):
    self._list_view.controls.clear()
    for entry in self.state.history:  # ← 无 _history_lock
        row = make_bubble_row(entry, self.state, self._bubble_max_width())
        ...
```

**触发条件**：
恢复自动存档时（`_on_autosave_prompt.restore`）或 `on_enter` 重灌历史时，loop 线程恰好正在 append。

**用户感知**：
deque maxlen=500，满时 append 会左侧 pop。迭代中左侧 pop 可能导致跳过元素或 `IndexError`（deque 迭代器在底层块被回收时行为未定义）。气泡列表可能缺少某些消息。被外层 `try/except` 吞掉，用户无感知。

**修复方向**：
改为 `for entry in self.state.history_snapshot():`（已有加锁方法）。

**验证建议**：
高并发：loop 线程持续 append + UI 线程调 `_reload_history_into_list`，确认无异常且消息数量正确。

---

### N7 用户回合发送后，导演输入栏可能因线程竞争而隐藏

**定位**：
- `app/components/director_input.py:137-141`（`_send` 中 `self.hide()`）
- `app/views/chat_view.py:629-633`（`_on_loop_event("resumed")` 中 `refresh` → `show("director")`）

**触发条件**：
1. 同时开启"用户模式"和"导演模式"
2. 轮到用户 → 输入文字 → 点发送
3. `send_user_message` 在 UI 线程执行 → `_user_turn_event.set()` 唤醒 loop 线程
4. UI 线程继续：`self._field.value=""` → `self.hide()`（`visible=False`）
5. Loop 线程并发：emit `"resumed"` → `_on_loop_event("resumed")` → `refresh` → `show("director")`（`visible=True`）

**用户感知**：
两个线程竞争修改同一个 `DirectorInput.root.visible`。若 UI 线程的 `hide()` 在 loop 线程的 `show("director")` 之后执行，导演输入栏被隐藏。用户发完言后本应看到导演输入栏，但它不见了。需切页面或再等一轮才恢复。

**根因分析**：
`_send` 中的 `self.hide()` 与 loop 线程的 `show("director")` 无同步保证。CPython GIL 不保证两个线程的操作顺序。

**修复方向**：
- `_send` 中用户模式发送后**不调** `self.hide()`，让 `"resumed"` 事件的 `refresh` 统一管理可见性
- 或在 `hide()` 中加 `if self.mode == "user": return` 守卫，防止 `"resumed"` 后的 `show` 被覆盖

**验证建议**：
开用户+导演模式，快速连续发送用户消息 10 次，确认每次发送后导演输入栏都正确显示。

---

### N8 存档页保存超时后取消订阅，实际成功的保存被"吞掉"

**定位**：`app/views/archives_view.py:381-386`

```python
def _save_timeout():
    import time as _t
    _t.sleep(30)
    if self._save_dialog:
        self._save_dialog.fail("保存超时，请重试")
    self._unsubscribe_save_events()  # ← 移除 saved handler
```

**触发条件**：
1. 存档页点"保存当前"
2. AI 标题生成慢但未超时（如 35s 后完成）
3. 30s 时 `_save_timeout` 触发

**用户感知**：
对话框显示"保存超时，请重试"。但实际上 `save_current_chat` 在 line 192 已经同步写入了初始数据（标题为"保存中..."）。35s 时 AI 标题生成完成，`_on_title_ready` 回写标题并 emit `"saved"` 事件。但 `archives_view` 已在 30s 时取消订阅，`"saved"` 事件无人处理。**文件已保存（标题为"保存中..."）但用户认为失败**。用户可能在存档列表中看到一个标题为"保存中..."的存档。

**根因分析**：
超时处理过于激进——取消订阅后，真正完成的保存事件被丢弃。初始数据已落盘但标题未更新。

**修复方向**：
- 超时后不取消订阅，仅标记"已超时"。若 `"saved"` 事件后续到达，更新对话框为"保存成功（延迟）"
- 或超时后仍保留订阅 60s，之后才真正清理
- 或在 `save_current_chat` 的初始写入时用 `_fallback_chat_title()` 而非"保存中..."，这样即使 AI 标题失败，标题也是合理的

**验证建议**：
模拟 API 延迟 35s → 存档页保存 → 确认 30s 时显示超时 → 35s 后确认对话框更新为成功（或至少存档标题不为"保存中..."）。

---

### N9 `load_chat` 替换 `app.history` 引用未加锁

**定位**：`core/chat_manager.py:263`

```python
app.history = deque(data.get("history", []), maxlen=500)  # ← 无 _history_lock
```

**触发条件**：
`load_chat` 被调用时 loop 线程仍在运行。目前 `archives_view._load._ok` 会先 `stop()` loop，但 `load_chat` 自身不做防御。

**用户感知**：
若未来有代码路径在不停止 loop 的情况下调 `load_chat`，loop 线程的 `with self.app._history_lock: self.app.history.append(entry)` 会 append 到旧 deque（引用已被替换），新消息丢失。

**根因分析**：
`load_chat` 直接替换 `app.history` 引用，不通过 `_history_lock`。lock 保护的是 deque 对象的读写，但引用替换绕过了 lock。

**修复方向**：
```python
with app._history_lock:
    app.history = deque(data.get("history", []), maxlen=500)
    app.turn_idx = data.get("turn_idx", 0)
    ...
```

**验证建议**：
确认所有 `load_chat` 调用路径都在 `loop.stop()` 之后（目前是），并加锁防御未来变更。

---

### N10 速度等待用 `_stop_event.wait` 导致高速度下暂停延迟最高 1 秒

**定位**：`core/dialogue_loop.py:363`

**这是首轮 #37 修复引入的轻微回归。**

```python
self._stop_event.wait(self.app.speed * 0.1)  # 速度 10 时等待 1 秒
```

**触发条件**：
速度设为 10（等待 1 秒），用户在等待期间点暂停。

**用户感知**：
`_stop_event.wait()` 只响应 stop 事件，不响应 pause。暂停在速度等待期间不会立即生效，需等到等待结束（最多 1 秒）。旧代码用 `for + sleep(0.1)` 每 0.1 秒检查一次暂停，响应更及时。

**根因分析**：
`_stop_event` 只在 `stop()` 时 `set()`，`pause()` 操作的是 `_paused`。速度等待用错了 Event。

**修复方向**：
改用 `self._paused.wait(timeout)` 配合循环：
```python
total = self.app.speed * 0.1
elapsed = 0.0
while elapsed < total and not self._stop_event.is_set():
    self._paused.wait(0.1)
    if not self._paused.is_set():
        break  # 已暂停，回到外层 while 的 _paused.wait()
    elapsed += 0.1
```

**验证建议**：
速度设 10 → 点暂停 → 确认 0.1 秒内暂停生效（而非 1 秒）。

---

## 第三章 · 边界与状态一致性（P2）⏳ 待修复

### N11 按时间生成场景失败后无错误反馈，静默回退

**定位**：`core/dialogue_loop.py:246-256`

`generate_time_scene_sync` 返回 `(None, err)` 时，loop 不 emit 任何错误事件，直接用 `current_scene=None` 继续。`_get_scene_text` 回退到最后一个静态场景。用户看到对话继续但场景标签仍是"按时间生成"，实际 prompt 用的是静态场景。

**修复方向**：失败时 emit `set_status` 显示错误，或回退 `scene_idx` 到 0。

---

### N12 `scene_banner._hide` 的二级 Timer 未被 `cancel()` 跟踪

**定位**：`app/components/scene_banner.py:100-110`

`_hide` 内启动 `threading.Timer(0.35, _set_invisible)` 赋给局部变量 `t`，未存到 `self._timer`。`cancel()` 只取消 `self._timer`（一级 Timer）。若 `cancel()` 在一级 Timer 触发后、二级 Timer 触发前调用，二级 Timer 仍会执行 `_set_invisible` → `page.update()`。离开页面后这次 `page.update()` 是多余的。

**修复方向**：将二级 Timer 也存为实例属性（如 `self._hide_timer`），`cancel()` 中一并取消。

---

### N13 `_parse_and_strip_scene_tag` 只剥离最后一个 [SCENE]，早期标签残留

**定位**：`core/ai_engine.py:244-260`

取 `scene_matches[-1]` 作为有效场景，但 `clean = text[:start] + text[end:]` 只剥离该标签。若 AI 输出两个 `[SCENE]...[/SCENE]`，第一个残留在对话文本中，用户看到 `[SCENE]...[/SCENE]` 字样。与 `[NEXT]` 的处理不一致（`[NEXT]` 用 `re.sub` 剥离所有）。

**修复方向**：统一剥离所有 `[SCENE]` 标签，取最后一个作为有效场景。

---

### N14 `_build_prompt` / `build_chat_title_prompt` 读取 history 未加锁

**定位**：`core/ai_engine.py:61, 483`；`core/chat_manager.py:221`

```python
recent = self.app.history[-8:] if self.app.history else []  # 无 _history_lock
```

`deque[-8:]` 创建副本（安全），但 `if self.app.history` 和 `[-8:]` 之间非原子。若 history 在两步之间被清空，`deque[-8:]` 返回 `[]`，但代码进入了 `len >= 4` 分支。结果 `recent=[]` → prompt 用空对话。

**修复方向**：统一用 `history_snapshot()` 或加锁。

---

### N15 `_handle_npc_logic` 读取 `history[-1]` 未加锁

**定位**：`core/dialogue_loop.py:377`

```python
last_msg = self.app.history[-1] if self.app.history else None
```

`deque[-1]` 在 deque 为空时抛 `IndexError`。`if self.app.history` 防御了空检查，但两步之间 deque 可能被清空（`stop()` 在另一线程调用 `history.clear()`）。`IndexError` 被外层 `except Exception` 吞掉，本轮 NPC 逻辑跳过。

**修复方向**：加锁或用 `try/except IndexError`。

---

### N16 用户回合期间 TransportBar 状态不正确

**定位**：`app/views/chat_view.py:617-620`

```python
def _on_user_turn(self, _data):
    self._user_turn = True
    self._update_status("轮到你了～", self.state.running, True)
    self._director_input.refresh(...)
    # ← 没有调 self._transport.set_running(True, True)
```

用户回合时 `loop.paused=True`，但 TransportBar 仍显示运行态（PAUSE 图标）。用户点 PAUSE → `pause()` 早退（line 114 `if self._waiting_for_user: return`）→ 无反馈。用户点 PLAY → `resume()` → "You" 在顺序中 → emit "轮到你了～" → 无变化。用户困惑。

**修复方向**：`_on_user_turn` 中调 `self._transport.set_running(True, True)` 显示暂停态。

---

### N17 `data_manager.load_profile` 对空场景列表注入假场景

**定位**：`core/data_manager.py:124-126`

```python
app.scenes = load_json(app.profile_dir / "scenes.json") or []
if not app.scenes:
    app.scenes = [{"time": "傍晚", "location": "", "scene": "一个普通的场景", "mood": "普通"}]
```

新建剧本的 `scenes.json` 是 `[]`。加载后用户看到剧本里多了一个"傍晚·一个普通的场景"。`prev_scene`/`next_scene` 的 `n==0` 守卫（#10 修复）成为死代码（scenes 永远 ≥1）。

**修复方向**：不注入假场景，让空列表保持空，UI 显示"暂无场景"。

---

### N18 复制角色不做唯一性校验

**定位**：`app/views/profiles_view.py:596-608`

```python
c["name"] = c.get("name", "char") + "_copy"
self.state.data._save_character(c["name"] + ".json", c)
```

连续复制"Lin"两次 → 都叫"Lin_copy" → 第二次覆盖第一次。

**修复方向**：复制时检查 `c["name"] + "_copy"` 是否已存在，冲突则追加 `_2`, `_3`（复用 `_make_safe_folder_name` 的后缀逻辑）。

---

## 第四章 · 代码质量与可维护性（P3）⏳ 待修复

### N19 `profiles_view._section_overview` 中 `cfg` 变量未使用

**定位**：`app/views/profiles_view.py:167`
`cfg = self.state._profile_config.get("app", {})` 取了但从未读取。死变量。

**修复方向**：删除该行。

---

### N20 `_npc_silent_turns == -1` 分支是死代码

**定位**：`core/dialogue_loop.py:412-413`
首轮 #18 修复将引入时初始化改为 0，但保留了 `== -1` 的兼容分支。所有初始化路径（`start`, `stop`, `_emit_random_result`）都设 0，此分支永不执行。

**修复方向**：删除 `if self.app._npc_silent_turns == -1:` 分支，保留 `else: self.app._npc_silent_turns += 1`。

---

### N21 `main_app.on_disconnect` 同步调用 `auto_save` 无 join 保护

**定位**：`app/main_app.py:68`
`page.on_disconnect = lambda e: app_state.auto_save()` — 同步 IO，Web 端可能未完成。且可能与 CLOSE 事件的 `auto_save` 线程竞争同一文件。

**修复方向**：与 CLOSE 统一处理，或加去重。

---

### N22 `profile_card.gather_profile_meta` 的 `load_json` 未传 default

**定位**：`app/components/profile_card.py:23, 28`
`load_json(pdir / "config.json")` 和 `load_json(pdir / "scenes.json")` 未传 `default`。首轮 #35 修复将 `load_json` 改为 `default=None`，但这两处靠 `or {}` / `or []` 兜底。功能正常但与修复后的风格不一致。

**修复方向**：改为 `load_json(..., default={})` 和 `load_json(..., default=[])`。

---

### N23 `_list_view.controls` 重新赋值可能不触发 Flet diff

**定位**：`app/views/chat_view.py:596`
`self._list_view.controls = self._list_view.controls[-300:]` 创建新 list 对象。Flet 可能不检测到子控件树变化。

**修复方向**：用 `del self._list_view.controls[:-300]` 原地修改。

---

### N24 `transport_bar._on_play_click` 用户回合时点 PLAY 无反馈

**定位**：`app/components/transport_bar.py:93-100` + `core/dialogue_loop.py:128-131`
用户回合时 `loop.paused=True` → 点 PLAY → `resume()` → "You" 在顺序中 → emit "轮到你了～" → 无 UI 变化。用户以为按钮坏了。

**修复方向**：`resume()` 中"You 在顺序中"分支 snack 提示"请先输入发言"，或 UI 层禁用 PLAY 按钮。

---

### N25 `AIEngine._build_prompt` 的 `recent` 可能含导演提示的方括号

**定位**：`core/ai_engine.py:64-73`
导演提示注入格式为 `[Director's note - ...]: text`，随机事件为 `[Something happened...]: text`，NPC 为 `[Passerby ... says]: text`。这些方括号在 `extract_json` 的 `else` 分支中可能被误识别为 JSON 数组起始（若 AI 回复包含这些 history 并混入 JSON）。实际场景中不太可能，但值得注意。

**修复方向**：在注入 history 时使用非方括号的分隔符，或在 `extract_json` 中优先尝试 `json.loads` 全文（已实现，但仅对纯 JSON 文本有效）。

---

## 附录 · 修复建议执行顺序

| 批次 | 编号 | 严重度 | 关键改动 |
|---|---|---|---|
| 1 | N1, N3 | P0 | ✅ 已完成：拼写错误 + 保存超时关闭对话框 |
| 2 | N2 | P0 | 活跃剧本详情页场景恢复 |
| 3 | N4, N5 | P1 | 设置页 `pc` 实时获取 + 改名迁移磁盘存档 |
| 4 | N6, N7, N9 | P1 | history 读取加锁 + 用户回合发送后输入栏竞争 |
| 5 | N8, N10 | P1 | 存档页超时不取消订阅 + 速度等待改用 `_paused.wait` |
| 6 | N11 ~ N18 | P2 | 边界条件与状态一致性 |
| 7 | N19 ~ N25 | P3 | 代码质量 |

---

## 附录 · 已确认的正常行为（修改时勿误伤）

继承首轮报告附录 B 的全部 15 条确认正常行为，此处不再重复。新增确认：

16. **`load_profile_for_edit` 不停止对话**：用于剧本详情页浏览/编辑，故意不清空当前对话。修改 N2 时注意保留此语义。
17. **`stop()` 中 `_clear_autosave()`**：停止对话时清除自动存档，避免下次启动弹出恢复提示。此为有意设计。
18. **`save_current_chat` 的初始写入**：先用"保存中..."标题同步落盘，再异步生成 AI 标题。此设计正确（防竞态），但 N8 中需考虑超时时的标题问题。

---

**报告结束。**

> 本报告由静态代码审查 + 修复回归分析 + 用户视角操作流程推演 + 线程时序分析生成。
> 所有问题定位均含 `file:line` 引用，修复方向为文字描述（不含代码 diff）。
> 修改时请对照"附录 · 已确认正常行为"避免误伤正确逻辑。
