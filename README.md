# ChatRoom · AI 角色扮演聊天室

> 多人 AI 角色扮演聊天应用 — 创建一个故事世界，让 AI 角色们自由对话，你可以扮演其中一个，也可以充当「导演」掌控全局。

ChatRoom 的前身是 Kivy 桌面应用 [ChatRoom](https://github.com/bowenzhang01/ChatRoom)，现已完全迁移至 **Flet** 框架（详见 [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md)），实现了：

- 🌐 **多平台支持** — Web / Windows / macOS / Linux / Android / iOS
- 🎨 **九色光谱主题** — 九种渐变色主题覆盖全光谱，浅色/深色随意切换
- ⚡ **流式输出** — LLM 逐 token 实时渲染，像打字一样流畅
- 🧠 **智能对话引擎** — 动态发言人选择、随机事件、路人 NPC、场景自动演化

![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![Flet](https://img.shields.io/badge/Flet-0.24+-purple)

---

## ✨ 核心功能

### 🤖 AI 角色扮演引擎

- **三种发言模式**：
  - `round` 轮流：按固定顺序依次发言
  - `random` 随机：每次随机选人
  - `dynamic` 动态：智能加权选人，含沉默惩罚（太久不说话概率↑）、直接点名（×3 权重）、[NEXT] 提示响应（×5 权重）、反自说自话（×0.1）
- **导演模式** — 随时注入旁白/指令到对话流中，角色们会自然地回应你的编排
- **用户模式** — 化身为剧本中的一个角色（`You`），和其他 AI 角色平等互动
- **动态场景** — AI 角色通过 `[SCENE]` 标签自动切换场景，时间、地点、氛围均可随对话推进而变化
- **发言速度可调** — 1-10 级速度滑块，控制角色发言间隔

### 🎲 随机事件 & 路人 NPC

对话不只是角色们在说话——世界也会发生意想不到的事情：

- **随机事件**：内置概率斜坡算法（冷却期 3 轮 + 概率爬升至 35%），自动触发环境变化（暴雨、停电、敲门声…）
- **路人 NPC**：随机生成临时路人角色，有名字、身份描述、独特性格
- **NPC 互动**：角色提及 NPC → NPC 回应 2-3 轮后自然离开；4 轮无人提及则默默退场
- **流式 NPC**：NPC 对话同样支持流式输出
- 所有随机事件参数内置默认值，在剧本设置中一键开关即可

### ⚡ 流式输出

- 角色发言通过 SSE (Server-Sent Events) 逐 token 实时渲染到聊天气泡
- NPC 对话同样走流式通道
- 设置中可随时关闭流式，切回一次性输出模式

### 📚 AI 一键创建剧本

输入一句话描述，AI 分四个阶段并行生成完整剧本：

| 阶段 | 内容 | 方式 |
|:---|:---|:---|
| **规划** | 世界观 + 标题 + 场景/角色提示 | 1 次 API 调用 |
| **场景** | 4 个完整场景（时间/地点/氛围/描述） | 4 次并行 API 调用 |
| **角色** | 4-5 个完整角色（人设/语气/外貌/系统提示） | 4-5 次并行 API 调用 |
| **组装** | 用户化身 + 剧本标题优化 | 2 次并行 API 调用 |

弹窗实时显示每个阶段的进度（如 `✓ 场景3/4 · ⏳ 角色2/5`），无需苦等。

除此之外还支持：
- **AI 补全角色** — 对已有角色一键补全缺失字段
- **AI 推断世界观** — 从标题和场景自动反推世界观
- **AI 生成场景** — 根据已有角色和世界观扩充新场景
- **AI 生成角色** — 根据场景和世界观生成新角色

### 🗣️ 发言顺序与模式

- **拖拽排序**：发言顺序通过拖拽列表自由调整
- **待命角色**：角色可在「待命」与「参与」之间拖拽切换
- **动态场景开关**：允许 AI 角色在发言中携带 `[SCENE]` 标签自动推进场景
- **随机事件开关**：独立控制，不影响其他模式

### 💾 对话存档

- **自动存档**：每次暂停和窗口关闭时自动保存，不丢一条消息
- **启动恢复**：检测到未保存对话时弹出恢复提示
- **AI 标题生成**：根据对话内容自动生成标题（如「深夜的寝室密谈」）
- **按日期分组**：今天/昨天/更早，一目了然
- **存档管理**：读取、删除、重命名

### 🎨 主题系统

九种渐变色主题，覆盖从赤红到紫罗兰的全光谱，每种包含完整的浅色/深色方案，在设置中随时切换：

| 极光 · 青→紫 | 暮光 · 粉→金 | 金穗 · 金→橙 | 翠微 · 绿系 | 海天 · 琥珀→青 |
|:---:|:---:|:---:|:---:|:---:|
| 碧落 · 天蓝 | 赤霞 · 红→玫 | 星夜 · 蓝→紫 | 虹光 · 全光谱 | — |

### 🔒 安全性

- **API Key 环境变量优先**：`DEEPSEEK_API_KEY` / `OPENAI_API_KEY` 环境变量 > config.json，避免密钥泄露到 Git
- **config.json 已 gitignore**：本地配置文件不会上传
- 支持自定义 API 地址，兼容任何 OpenAI 接口兼容的服务

---

## 🏗️ 项目架构

```
dorm-flet/
├── main.py                    # 入口脚本
├── config.py                  # 全局配置 & 路径常量
├── utils.py                   # 纯工具（JSON/颜色/流解析）
│
├── core/                      # 业务层（零 UI 依赖，可独立复用）
│   ├── app_state.py           # 全局状态中心
│   ├── ai_engine.py           # AI 引擎（prompt 构建/LLM 调用/标签解析）
│   ├── dialogue_loop.py       # 对话主循环（后台线程 + 流式管线）
│   ├── chat_manager.py        # 存档管理（读写/自动存档/恢复）
│   ├── data_manager.py        # 剧本 CRUD（角色/场景/配置）
│   ├── events.py              # EventBus 事件总线
│   └── debug.py               # 调试工具（DEBUG=dorm 启用）
│
├── services/                  # 服务层
│   ├── api_service.py         # LLM HTTP（同步/异步/SSE 流式）
│   └── path_resolver.py       # 平台路径（开发/打包/移动端）
│
├── app/                       # UI 层（Flet）
│   ├── main_app.py            # 应用组装入口
│   ├── theme.py               # 九色光谱主题（渐变/配色令牌）
│   ├── router.py              # 响应式导航（桌面 Rail / 手机 NavBar）
│   ├── state.py               # UI 反应式状态
│   ├── views/                 # 四个主视图
│   │   ├── chat_view.py       # 聊天（气泡/流式渲染/回底按钮）
│   │   ├── profiles_view.py   # 剧本管理（卡片网格/详情/拖拽）
│   │   ├── archives_view.py   # 对话存档
│   │   └── settings_view.py   # 设置（API/外观/行为/关于）
│   └── components/            # 可复用组件
│
├── profiles/                  # 预设剧本
│   ├── dorm_life/             # 女生寝室·日常（5 角色 + 4 场景）
│   └── starship/              # 星际飞船（5 角色 + 5 场景）
│
└── assets/                    # 字体等静态资源
```

### 设计特点

- **core ↔ UI 彻底解耦**：业务层不含任何 Flet/Kivy 引用，换 UI 框架零成本
- **EventBus 事件驱动**：后台线程 emit 事件 → UI handler 更新控件，无轮询
- **线程安全**：Flet `page.update()` 跨线程安全，事件回调直接更新 UI
- **流式管线**：`msg → msg_delta(多次) → msg_end`，和非流式模式共用渲染逻辑

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- DeepSeek API Key（或兼容 OpenAI 接口的其他 LLM 服务）

### 1. 安装

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config.example.json config.json
```

编辑 `config.json`，填入 API Key：

```json
{
  "model": {
    "api_key": "sk-你的Key",
    "api_base": "https://api.deepseek.com",
    "model": "deepseek-v4-flash"
  },
  "active_profile": "dorm_life"
}
```

> 💡 也可设置环境变量 `DEEPSEEK_API_KEY`，优先级高于配置文件，更安全。

### 3. 运行

```bash
# Web 模式（推荐开发调试）
flet run main.py --web --port 8080

# 桌面模式
flet run main.py
```

### 调试模式

```bash
# Windows
$env:DEBUG="dorm"; flet run main.py

# Linux / macOS
DEBUG=dorm flet run main.py
```

---

## 📦 构建发布

```bash
flet build web      # Web 部署
flet build windows  # Windows 桌面
flet build macos    # macOS
flet build apk      # Android
flet build ios      # iOS
```

---

## 🎮 使用指南

### 快速上手

1. **设置 API Key** → 进入设置页，填写 API 地址和 Key，测试连接
2. **选择剧本** → 内置「女生寝室·日常」和「星际飞船」两个预设剧本
3. **开始对话** → 点击 ▶ 按钮，角色们开始自主对话
4. **介入对话** → 开启导演模式发指令，或开启用户模式以角色身份加入
5. **保存** → 对话自动存档，也可手动保存

### AI 创建新剧本

进入剧本页 → 点击「✨ AI 创建」 → 输入描述（如「赛博朋克酒吧的深夜」） → 等待多阶段生成完成即可开始新故事。

---

## 🛠️ 技术栈

| 层级 | 技术 | 说明 |
|:---|:---|:---|
| UI | [Flet](https://flet.dev) | Flutter in Python |
| 网络 | [httpx](https://www.python-httpx.org) | HTTP + SSE 流式 |
| AI | DeepSeek API | OpenAI 兼容接口 |
| 字体 | Noto Sans SC | 中文渲染 |
| 打包 | Flet build | 多平台一键构建 |

---

## 📝 迁移历史

本项目从 Kivy 版 [ChatRoom](https://github.com/bowenzhang01/ChatRoom) 完全重写而来，迁移的技术细节和 UI 设计规格见 [IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md)。

关键里程碑：
- **Kivy → Flet 全量迁移** — UI 层完全重写，core 层零依赖保留
- **EventBus 替代 Queue+Clock 轮询** — 更简洁的事件驱动架构
- **流式输出** — SSE 逐 token 渲染，支持中途开关
- **AI 生成重构** — 单次 API 调用 → 多阶段并行 + 进度追踪
- **九色主题** — 单一 Indigo → 覆盖全光谱

---

## 📄 许可证

MIT License
