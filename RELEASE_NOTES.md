# ChatRoom v1.0.0 🎉

> AI 多人角色扮演聊天室 — 首个正式发布版本，支持 Android / Windows 双平台。

---

## 📦 下载

| 平台 | 文件 | 大小 |
|------|------|------|
| 📱 Android | `chatroom-for-android.apk` | ~159 MB |
| 🪟 Windows 安装包 | `chatroom-for-windows-setup.exe` | ~300 MB |

---

## ✨ 核心功能

- 🤖 **AI 角色扮演引擎** — 三种发言模式（轮流/随机/动态），智能加权选人
- 🎬 **导演模式** — 随时注入旁白，掌控对话走向
- 👤 **用户模式** — 化身角色参与对话
- 🎲 **随机事件 & 路人 NPC** — 概率斜坡算法，世界自发演化
- 📚 **AI 一键创建剧本** — 输入一句话，四阶段并行生成完整剧本（世界观+场景+角色）
- ⚡ **流式输出** — LLM 逐 token 实时渲染
- 🎨 **九色光谱主题** — 浅色/深色双模式
- 💾 **对话存档** — 自动存档 + 启动恢复 + AI 标题生成
- 📱 **响应式布局** — 桌面 Rail 导航 / 手机 NavBar 自适应切换

---

## 🔧 技术栈

- **Flet 0.86.0** + Flutter 3.44.4
- **DeepSeek API**（兼容 OpenAI 接口）
- **serious_python** 打包

---

## 📝 本版本改动

- 项目正式更名为 **ChatRoom**（原 dorm-flet）
- Android 包名更新为 `com.flet.chatroom`
- Windows 安装包使用 Inno Setup，支持开始菜单 + 卸载
- 应用数据目录迁移至 `%APPDATA%/chatroom`
- 多项 UI 响应式适配修复
