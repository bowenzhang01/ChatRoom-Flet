# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · 对话存档管理器
   迁移自 Kivy 版 core/chat_manager.py，零 UI 框架依赖。
   - 业务逻辑（存档读写 / AI 标题生成 / 自动存档 / 启动恢复检测）保留
   - 所有 UI 弹窗代码删除（保存中/保存成功/恢复询问）
     改由 EventBus 通知 UI 层：
       "saving"          → 正在保存（UI 显示进度）
       "saved"           → 保存完成 (val={title, success, path})
       "autosave_prompt" → 启动时检测到自动存档 (val={title, message_count, path})

   v2 文件夹格式：每个存档是一个目录，内含 chat.json + images/
     向后兼容旧的单文件 .json 存档（只读，下次保存自动迁移）。
"""

import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from utils import load_json, save_json, extract_json
from services.api_service import call_chat_completion_async


def _resolve_chat_json(chat_path: Path) -> Path:
    """解析存档路径，返回 chat.json 的实际文件路径。

    - 新格式（目录）：chat_path 是目录 → chat_path/chat.json
    - 旧格式（文件）：chat_path 是 .json 文件 → chat_path 本身
    """
    if chat_path.is_dir():
        return chat_path / "chat.json"
    return chat_path


def _is_legacy_format(chat_path: Path) -> bool:
    return chat_path.is_file() and chat_path.suffix == ".json"


class ChatManager:
    """对话存档管理 — 通过 app 引用读取状态，通过 bus 通知 UI。"""

    def __init__(self, app):
        self.app = app
        self.bus = app.bus
        self._loaded_chat_path = None   # 目录路径（新格式）或 None（新对话）
        self._last_save_time = 0.0
        self._last_autosave_len = 0
        self._last_saved_count = -1

    @property
    def chats_dir(self) -> Path:
        active = config.app_config.get("active_profile", "")
        if active:
            return config.PROFILES_DIR / active / "chats"
        return self.app.profile_dir / "chats" if self.app.profile_dir else None

    def _ensure_chats_dir(self):
        if self.chats_dir and not self.chats_dir.exists():
            self.chats_dir.mkdir(parents=True, exist_ok=True)

    @property
    def active_images_dir(self) -> Optional[Path]:
        """当前对话会话的图像目录。优先加载档目录，否则用 _active/ 临时目录。"""
        if self._loaded_chat_path is not None:
            return self._loaded_chat_path / "images"
        if self.chats_dir is None:
            return None
        self._ensure_chats_dir()
        active_dir = self.chats_dir / "_active"
        active_dir.mkdir(parents=True, exist_ok=True)
        return active_dir / "images"

    def chat_images_dir(self, chat_path: Optional[Path] = None) -> Optional[Path]:
        """获取某存档目录下的 images/ 目录路径。

        若未传 chat_path，用当前加载的存档目录。
        """
        if chat_path is None:
            chat_path = self._loaded_chat_path
        if chat_path is None:
            return None
        if _is_legacy_format(chat_path):
            return chat_path.parent / "images"
        return chat_path / "images"

    # ── 列表与元信息 ──

    def _list_chat_dirs(self):
        """列出新格式存档目录 + 旧格式 .json 文件，按时间戳倒序。"""
        if not self.chats_dir or not self.chats_dir.exists():
            return []

        results = []
        seen = set()

        for entry in sorted(self.chats_dir.iterdir(), key=lambda e: e.name, reverse=True):
            if entry.name.startswith(".") or entry.name == "_autosave":
                continue
            if entry.is_dir():
                json_path = entry / "chat.json"
                if json_path.exists():
                    results.append(entry)
                    seen.add(entry.name)
            elif entry.is_file() and entry.suffix == ".json":
                name = entry.stem
                if name not in seen:
                    results.append(entry)

        def _sort_key(p):
            m = re.search(r'chat_(\d{8}_\d{6})', p.name)
            return m.group(1) if m else "00000000_000000"
        results.sort(key=_sort_key, reverse=True)
        return results

    def list_autosave(self):
        """获取自动存档路径（若存在且非空）。"""
        if not self.chats_dir:
            return None
        # 新格式
        new_path = self.chats_dir / "_autosave"
        if new_path.is_dir():
            json_path = new_path / "chat.json"
            if json_path.exists():
                data = load_json(json_path)
                if data and data.get("history"):
                    return new_path
        # 旧格式
        old_path = self.chats_dir / "_autosave.json"
        if old_path.exists():
            data = load_json(old_path)
            if data and data.get("history"):
                return old_path
        return None

    def _read_chat_meta(self, chat_path):
        """读取存档的元信息（title, message_count, created_at）。"""
        try:
            data = load_json(_resolve_chat_json(chat_path))
            if not data:
                return None
            is_autosave = chat_path.name in ("_autosave", "_autosave.json")
            return {
                "title": data.get("title", chat_path.stem),
                "message_count": data.get("message_count", 0),
                "created_at": data.get("created_at", ""),
                "is_autosave": is_autosave,
            }
        except Exception:
            return None

    def list_chats_with_meta(self):
        result = []
        autosave = self.list_autosave()
        if autosave:
            meta = self._read_chat_meta(autosave)
            if meta:
                result.append((autosave, meta))
        for p in self._list_chat_dirs():
            meta = self._read_chat_meta(p)
            if meta:
                result.append((p, meta))
        return result

    def list_chats_for_profile(self, folder: str):
        chats_dir = config.PROFILES_DIR / folder / "chats"
        if not chats_dir.exists():
            return []

        result = []
        auto = chats_dir / "_autosave"
        if auto.is_dir() and (auto / "chat.json").exists():
            data = load_json(auto / "chat.json")
            if data and data.get("history"):
                meta = self._read_chat_meta(auto)
                if meta:
                    result.append((auto, meta))
        auto_old = chats_dir / "_autosave.json"
        if auto_old.exists():
            data = load_json(auto_old)
            if data and data.get("history"):
                meta = self._read_chat_meta(auto_old)
                if meta:
                    result.append((auto_old, meta))

        entries = sorted(chats_dir.iterdir(), key=lambda e: e.name, reverse=True)
        seen = set()
        for entry in entries:
            if entry.name.startswith(".") or entry.name == "_autosave":
                continue
            if entry.is_dir():
                if (entry / "chat.json").exists():
                    meta = self._read_chat_meta(entry)
                    if meta:
                        result.append((entry, meta))
                    seen.add(entry.name)
            elif entry.is_file() and entry.suffix == ".json":
                if entry.stem not in seen:
                    meta = self._read_chat_meta(entry)
                    if meta:
                        result.append((entry, meta))

        return result

    # ── 保存 ──

    def _save_chat_to_dir(self, chat_dir: Path, title: str):
        """将当前对话写入 chat_dir/chat.json。"""
        chat_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "title": title,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_count": len(self.app.history),
            "scene_idx": self.app.scene_idx,
            "current_scene": self.app.current_scene,
            "turn_idx": self.app.turn_idx,
            "turn_count": self.app.turn_count,
            "history": self.app.history_snapshot(),
        }
        return save_json(chat_dir / "chat.json", data)

    def _fallback_chat_title(self) -> str:
        ac = self.app._profile_config.get("app", {})
        profile_name = ac.get("title", self.app.title)
        scene_time = ""
        if self.app.scene_idx >= 0 and self.app.scenes and self.app.scene_idx < len(self.app.scenes):
            scene_time = self.app.scenes[self.app.scene_idx].get("time", "")
        elif self.app.current_scene:
            scene_time = self.app.current_scene.get("time", "")
        now = datetime.now().strftime("%H:%M")
        parts = [profile_name]
        if scene_time:
            parts.append(scene_time)
        parts.append(now)
        return " - ".join(parts)

    def save_current_chat(self, show_feedback=True):
        if not self.app.history:
            if show_feedback:
                self.bus.emit("saved", {"title": "", "success": False,
                                         "message": "没有对话内容可保存", "path": None})
            return

        self._ensure_chats_dir()

        if self._loaded_chat_path is not None:
            chat_dir = self._loaded_chat_path
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            chat_dir = self.chats_dir / f"chat_{ts}"

        chat_dir.mkdir(parents=True, exist_ok=True)

        saved_data = {
            "title": self._fallback_chat_title(),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_count": len(self.app.history),
            "scene_idx": self.app.scene_idx,
            "current_scene": self.app.current_scene,
            "turn_idx": self.app.turn_idx,
            "turn_count": self.app.turn_count,
            "history": self.app.history_snapshot(),
        }
        save_json(chat_dir / "chat.json", saved_data)
        self._loaded_chat_path = chat_dir

        if show_feedback:
            self.bus.emit("saving", None)

        _caller_profile = config.app_config.get("active_profile", "")

        def _on_title_ready(title):
            saved_data["title"] = title
            saved_data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_json(chat_dir / "chat.json", saved_data)
            self._last_save_time = time.time()
            self._last_saved_count = len(saved_data.get("history", []))
            self._last_autosave_len = self._last_saved_count
            if config.app_config.get("active_profile", "") == _caller_profile:
                self._clear_autosave()
            else:
                self._clear_autosave(chat_dir)
            if show_feedback:
                self.bus.emit("saved", {"title": title, "success": True,
                                         "message": "保存成功", "path": str(chat_dir)})

        self._generate_chat_title(_on_title_ready)

    def _generate_chat_title(self, callback):
        recent = self.app.history_snapshot()[-6:] if len(self.app.history) >= 4 else self.app.history_snapshot()
        if not recent or not config.API_KEY:
            callback(self._fallback_chat_title())
            return

        prompt = self.app.ai.build_chat_title_prompt()

        def _on_title_result(content):
            result, err = extract_json(content)
            if result and result.get("title"):
                callback(result["title"].strip())
            else:
                print(f"[chat] 标题 JSON 提取失败: {err}")
                callback(self._fallback_chat_title())

        def _on_title_error(err):
            print(f"[chat] 标题 API 异常: {err}")
            callback(self._fallback_chat_title())

        call_chat_completion_async(
            messages=[
                {"role": "system", "content": "你是一个对话标题生成器，只返回JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=300,
            timeout=15.0,
            on_result=_on_title_result,
            on_error=_on_title_error,
        )

    # ── 读取 ──

    def load_chat(self, chat_path) -> bool:
        """读取对话存档，恢复历史到 app 状态。

        chat_path 可以是：
        - 目录（新格式）→ 读取 chat.json
        - .json 文件（旧格式）→ 直接读取，但不设置 _loaded_chat_path
          （下次保存时自动迁移到新格式）

        返回 True 成功 / False 失败。
        """
        chat_path = Path(chat_path)
        json_path = _resolve_chat_json(chat_path)
        data = load_json(json_path)
        if not data or "history" not in data:
            return False

        from collections import deque
        app = self.app
        with app._history_lock:
            app.history = deque(data.get("history", []), maxlen=500)
            app.turn_idx = data.get("turn_idx", 0)
            app.turn_count = data.get("turn_count", 0)
            app.message_count = data.get("message_count", len(app.history))
        app._char_last_turn = {}
        for i, entry in enumerate(reversed(app.history)):
            name = entry.get("name", "")
            if name and name not in app._char_last_turn:
                app._char_last_turn[name] = app.turn_count - i
        app._suggested_next = None
        saved_scene = data.get("scene_idx", 0)
        if 0 <= saved_scene < len(app.scenes):
            app.scene_idx = saved_scene
        saved_current_scene = data.get("current_scene")
        if saved_current_scene:
            app.current_scene = saved_current_scene

        # 新格式：目录路径；旧格式：不移入 loaded，下次保存自动迁移
        if chat_path.is_dir():
            self._loaded_chat_path = chat_path
        else:
            self._loaded_chat_path = None

        self._last_saved_count = len(app.history)
        self._last_autosave_len = len(app.history)
        return True

    def delete_chat(self, chat_path) -> bool:
        try:
            chat_path = Path(chat_path)
            if chat_path.is_dir():
                shutil.rmtree(chat_path)
            else:
                chat_path.unlink()
            return True
        except Exception as e:
            print(f"[chat] 删除失败: {e}")
            return False

    # ── 自动存档 ──

    def _auto_save(self):
        if not self.app.history:
            return
        if len(self.app.history) == self._last_autosave_len:
            return
        self._ensure_chats_dir()
        if not self.chats_dir:
            return
        autosave_dir = self.chats_dir / "_autosave"
        title = self._fallback_chat_title()
        self._save_chat_to_dir(autosave_dir, title)
        self._last_autosave_len = len(self.app.history)
        self._last_saved_count = len(self.app.history)
        self._last_save_time = time.time()

    def _clear_autosave(self, chats_dir=None):
        target = Path(chats_dir) if chats_dir else self.chats_dir
        if not target:
            return
        # 新格式目录
        autosave_dir = target / "_autosave"
        if autosave_dir.is_dir():
            try:
                shutil.rmtree(autosave_dir)
            except Exception:
                pass
        # 旧格式文件
        old = target / "_autosave.json"
        if old.exists():
            try:
                old.unlink()
            except Exception:
                pass

    def has_unsaved_messages(self) -> bool:
        if not self.app.history:
            return False
        if self._last_saved_count < 0:
            return True
        return len(self.app.history) != self._last_saved_count

    def check_autosave_on_start(self):
        if not self.chats_dir:
            return
        target = self.chats_dir / "_autosave"
        json_path = target / "chat.json" if target.is_dir() else None
        old_path = self.chats_dir / "_autosave.json"

        data = None
        path = None
        if json_path and json_path.exists():
            data = load_json(json_path)
            path = str(target)
        elif old_path.exists():
            data = load_json(old_path)
            path = str(old_path)

        if not data or not data.get("history"):
            self._clear_autosave()
            return
        self.bus.emit("autosave_prompt", {
            "title": data.get("title", "自动存档"),
            "message_count": data.get("message_count", 0),
            "path": path,
        })

    def restore_autosave(self, path: str) -> bool:
        ok = self.load_chat(Path(path))
        if ok:
            self._clear_autosave()
            self._loaded_chat_path = None
        return ok

    def discard_autosave(self, path: str):
        try:
            p = Path(path)
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        except Exception:
            pass
