# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · 数据管理器
  迁移自 Kivy 版 core/data_manager.py，零 UI 框架依赖。
  - 移除 self.app._set_status 调用（改为返回 bool，由 UI 层决定提示）
  - 移除 welcome_title / welcome_text 默认值（应用户要求废弃该字段）
  - 保留：profile 加载 / 迁移 / CRUD / 发言顺序管理
"""

import json
import os
from pathlib import Path

import config
from utils import load_json, save_json


class DataManager:
    """数据管理器 — 通过 app 引用读写状态，不直接操作 UI。"""

    def __init__(self, app):
        self.app = app

    # ── 迁移 ──

    def _migrate_if_needed(self):
        """首次启动时自动将旧扁平数据迁移到 profiles/ 下。
        （保留向后兼容，原项目历史数据可平滑迁入）"""
        if not config.PROFILES_DIR.exists() or not any(
            p.is_dir() for p in config.PROFILES_DIR.iterdir()
        ):
            # 仅当无活跃剧本或活跃剧本目录不存在时才执行迁移
            active = config.app_config.get("active_profile", "")
            if active and (config.PROFILES_DIR / active).is_dir():
                return
            default_name = "dorm_life"
            default_profile = config.PROFILES_DIR / default_name
            default_profile.mkdir(parents=True, exist_ok=True)
            (default_profile / "characters").mkdir(exist_ok=True)

            old_scenes = config.BASE_DIR / "scenes.json"
            if old_scenes.exists():
                import shutil
                shutil.copy(str(old_scenes), str(default_profile / "scenes.json"))

            old_chars = config.BASE_DIR / "characters"
            if old_chars.exists():
                import shutil
                for f in old_chars.glob("*.json"):
                    shutil.copy(str(f), str(default_profile / "characters" / f.name))

            old_ac = config.app_config.get("app", {})
            old_turn = config.app_config.get("turn", {})
            profile_config_data = {
                "app": {
                    "title": old_ac.get("title", "ChatRoom"),
                    # welcome_title / welcome_text 已废弃，不再迁移
                    "director_mode": old_ac.get("director_mode", False),
                    "user_mode": old_ac.get("user_mode", False),
                    "dynamic_scene": old_ac.get("dynamic_scene", False),
                    "random_event": False,
                },
                "turn": {
                    "order": old_turn.get("order", []),
                    "history_size": old_turn.get("history_size", 8),
                },
                "speed": {"default": config.app_config.get("speed", {}).get("default", 3)},
            }
            save_json(default_profile / "config.json", profile_config_data)

            if "active_profile" not in config.app_config:
                config.app_config["active_profile"] = default_name
                save_json(config.BASE_DIR / "config.json", config.app_config)

            print(f"[data] 已自动迁移数据到 profiles/{default_name}/")

    # ── Profile 加载 ──

    def load_profile(self, profile_name):
        """动态加载指定剧本的所有数据到 app 状态。"""
        app = self.app
        app.profile_dir = config.PROFILES_DIR / profile_name
        app.char_dir = app.profile_dir / "characters"

        app.profile_dir.mkdir(parents=True, exist_ok=True)
        app.char_dir.mkdir(parents=True, exist_ok=True)
        (app.profile_dir / "chats").mkdir(exist_ok=True)

        app._profile_config = load_json(app.profile_dir / "config.json", default={})
        ac = app._profile_config.get("app", {})
        tc = app._profile_config.get("turn", {})
        sc = app._profile_config.get("speed", {})

        app.title = ac.get("title", profile_name)
        app.turn_order = list(tc.get("order", []))
        app._raw_turn_order = app.turn_order
        app.speed = max(1, min(10, sc.get("default", 3)))
        # 发言模式从剧本配置读取（回退到 round）
        mc = app._profile_config.get("mode", {})
        app.mode = mc.get("default", "round") if mc.get("default", "round") in ("round", "random", "dynamic") else "round"
        app.director_mode = ac.get("director_mode", False)
        app.user_mode = ac.get("user_mode", False)
        app.dynamic_scene_enabled = ac.get("dynamic_scene", False)

        # 随机事件状态（参数用 config 默认值，不从 profile 读取）
        app.random_event_enabled = ac.get("random_event", False)
        # 向后兼容：旧配置将 random_event 放在顶层（dict 带 enabled 字段），迁移到 app 下
        top_random = app._profile_config.get("random_event")
        if isinstance(top_random, dict):
            app.random_event_enabled = top_random.get("enabled", False)
            ac["random_event"] = app.random_event_enabled
            del app._profile_config["random_event"]
            try:
                save_json(app.profile_dir / "config.json", app._profile_config)
            except Exception:
                pass
        app._last_random_event_turn = 0
        app._char_turns_since_event = 0
        app._active_npc = None
        app._npc_silent_turns = 0
        app._npc_rounds_left = 0

        # 加载场景
        app.scenes = load_json(app.profile_dir / "scenes.json") or []
        app.scene_idx = 0 if app.scenes else -1

        # 加载角色
        self._reload_data()

        # 过滤发言顺序，只保留存在的角色（含 You）
        valid = set(app.characters.keys())
        if hasattr(app, '_raw_turn_order'):
            app.turn_order = [n for n in app._raw_turn_order if n in valid]
            del app._raw_turn_order
        else:
            app.turn_order = [n for n in app.turn_order if n in valid]

        # 用户模式开启且 You 存在但不在顺序中 → 自动追加
        if app.user_mode and "You" in app.characters and "You" not in app.turn_order:
            app.turn_order.append("You")

        app.current_scene = None
        app.scene_version = 0
        app._last_scene_update_turn = -1

        from core.debug import validate_profile
        validate_profile(app)

    # ── Profile 查询 ──

    def get_profile_list(self):
        """获取所有可用剧本名称列表（按 config.json 修改时间倒序）"""
        if not config.PROFILES_DIR.exists():
            return ["dorm_life"]
        profiles = []
        for p in config.PROFILES_DIR.iterdir():
            if p.is_dir() and (p / "config.json").exists():
                mtime = (p / "config.json").stat().st_mtime
                profiles.append((p.name, mtime))
        profiles.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in profiles] or ["dorm_life"]

    def get_profile_display_names(self):
        """获取剧本显示名称列表（用于 UI 下拉）"""
        return [self.profile_name_to_display(pn) for pn in self.get_profile_list()]

    def profile_name_to_display(self, folder_name):
        """文件夹名 → 显示名"""
        pc = load_json(config.PROFILES_DIR / folder_name / "config.json", default={})
        return pc.get("app", {}).get("title", pc.get("app", {}).get("display_name", folder_name))

    def profile_display_to_name(self, display_name):
        """显示名 → 文件夹名"""
        for pn in self.get_profile_list():
            if self.profile_name_to_display(pn) == display_name:
                return pn
        return display_name

    # ── 数据 I/O（全部返回 bool，UI 层负责提示）──

    def _safe_write(self, path, data, desc=""):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[data] 保存失败 {desc}: {e}")
            return False

    def _save_scenes(self):
        return self._safe_write(
            self.app.profile_dir / "scenes.json", list(self.app.scenes), "scenes"
        )

    def _save_config(self):
        return save_json(config.BASE_DIR / "config.json", config.app_config)

    def _save_turn_order(self):
        pc = self.app._profile_config
        pc.setdefault("turn", {})["order"] = self.app.turn_order
        return save_json(self.app.profile_dir / "config.json", pc)

    def _save_profile_config(self):
        """保存整个 profile_config.json（剧本级配置）"""
        return save_json(self.app.profile_dir / "config.json", self.app._profile_config)

    def _save_character(self, filename, data):
        if not self.app.char_dir:
            return False
        self.app.char_dir.mkdir(parents=True, exist_ok=True)
        return self._safe_write(self.app.char_dir / filename, data, "character")

    def _delete_character(self, name):
        if not self.app.char_dir:
            return False
        fpath = self.app.char_dir / (name + ".json")
        if fpath.exists():
            fpath.unlink()
            return True
        return False

    def _migrate_character_in_chats(self, old_name, new_name,
                                     old_display_name=None, new_display_name=None):
        """迁移所有聊天存档中的角色名/显示名引用。"""
        chats_dir = self.app.profile_dir / "chats"
        if not chats_dir.exists():
            return
        for f in list(chats_dir.glob("chat_*.json")) + list(chats_dir.glob("_autosave.json")):
            try:
                data = load_json(f)
                if not data or "history" not in data:
                    continue
                modified = False
                for entry in data["history"]:
                    if entry.get("name") == old_name:
                        entry["name"] = new_name
                        modified = True
                    if (old_display_name and new_display_name
                            and entry.get("display_name") == old_display_name):
                        entry["display_name"] = new_display_name
                        modified = True
                if modified:
                    save_json(f, data)
            except Exception:
                pass

    def _reload_data(self):
        """从当前剧本目录重新加载角色/样式。"""
        app = self.app
        if not app.char_dir:
            return
        new_chars = {}
        new_styles = {}
        char_load_errors = []
        if app.char_dir.exists():
            for f in sorted(app.char_dir.glob("*.json")):
                try:
                    c = json.loads(f.read_text("utf-8"))
                    new_chars[c["name"]] = c
                except Exception as e:
                    char_load_errors.append(f.name)
                    print(f"[data] 角色加载失败 {f.name}: {e}")
        app._char_load_errors = char_load_errors
        for c in new_chars.values():
            new_styles[c["name"]] = {
                "color": c.get("color", "#888"),
                "bg": c.get("bg_color", "#f5f5f5"),
                "name": c.get("display_name", c["name"]),
            }
        app.characters = new_chars
        app.char_styles = new_styles

    # ── 剧本管理 ──

    def _make_safe_folder_name(self, display_name: str) -> str:
        """中文显示名 → 安全英文文件夹名。ASCII 保留，其他用 md5 前 8 位。
        冲突时自动追加 _2, _3 后缀。"""
        import hashlib
        safe = "".join(c for c in display_name if c.isascii() and (c.isalnum() or c == "_"))
        if safe and not safe[0].isdigit():
            base = safe.lower()
        else:
            base = "profile_" + hashlib.md5(display_name.encode("utf-8")).hexdigest()[:8]
        candidate = base
        idx = 1
        while (config.PROFILES_DIR / candidate).exists():
            idx += 1
            candidate = f"{base}_{idx}"
        return candidate

    def create_profile(self, display_name: str) -> str:
        """新建剧本。返回文件夹名（成功）或空字符串（失败）。"""
        folder = self._make_safe_folder_name(display_name)
        pdir = config.PROFILES_DIR / folder
        if pdir.exists():
            return ""
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "characters").mkdir(exist_ok=True)
        (pdir / "chats").mkdir(exist_ok=True)
        save_json(pdir / "config.json", {
            "app": {"title": display_name},
            "turn": {"order": [], "history_size": 8},
            "speed": {"default": 3},
            "world": {"setting": ""},
        })
        save_json(pdir / "scenes.json", [])
        save_json(pdir / "characters" / "You.json", {
            "name": "You",
            "display_name": "你",
            "color": "#42a5f5",
            "bg_color": "#f0f7ff",
            "personality": "你自己",
            "description": "就是你自己～一个和大家一起生活的普通人。",
            "system_prompt": "你是这个世界的一员，和伙伴们自然地聊天。对话内容用直角引号「」包裹，动作描写用*星号*包裹，例如：*伸了个懒腰*、*笑着拍拍她的肩*。回复简短自然，100-200字。",
        })
        return folder

    def delete_profile(self, folder_name: str) -> bool:
        """删除剧本（至少保留一个）"""
        import shutil
        if len(self.get_profile_list()) <= 1:
            return False
        pdir = config.PROFILES_DIR / folder_name
        if pdir.exists() and pdir.is_dir():
            shutil.rmtree(str(pdir))
            return True
        return False

    def rename_profile(self, folder_name: str, new_display_name: str) -> bool:
        """重命名剧本（仅改 config.json 的 title 字段）"""
        pc_path = config.PROFILES_DIR / folder_name / "config.json"
        pc = load_json(pc_path, default={})
        pc.setdefault("app", {})["title"] = new_display_name
        return save_json(pc_path, pc)
