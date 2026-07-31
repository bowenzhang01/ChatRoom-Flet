# -*- coding: utf-8 -*-
"""
ChatRoom - Flet Edition · ComfyUI 图像生成器
    - 管理 ComfyUI 子进程生命周期（启动 / 停止）
    - 加载 API 格式工作流模板，注入 prompt + 参数后提交
    - 同步等待生成完成，复制图片到 chat images 目录并创建缩略图
    - 在对话 loop 线程中同步调用 generate()
"""

import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from services.api_service import call_chat_completion, APIError
import config


class ImageGenerator:
    """ComfyUI 图像生成器。"""

    def __init__(self, app):
        self.app = app
        self._process: Optional[subprocess.Popen] = None
        self._ready = False
        self._workflow_template: Optional[dict] = None
        self._node_map: dict = {}
        self._scan_errors: list = []

    @property
    def ready(self) -> bool:
        return self._ready

    # ═══ ComfyUI 生命周期 ═══

    def _check_api(self) -> bool:
        try:
            url = f"http://{config.COMFYUI_HOST}:{config.COMFYUI_PORT}/system_stats"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                json.loads(resp.read())
            return True
        except urllib.error.URLError as e:
            pass
        except Exception:
            pass
        return False

    def start(self) -> bool:
        """启动 ComfyUI 子进程，等待 API 就绪。"""
        bus = self.app.bus

        if self._check_api():
            print("[image_gen] ComfyUI 已在运行")
            self._ready = True
            bus.emit("comfyui_status", {"stage": "ready", "detail": "ComfyUI 已就绪"})
            return True

        comfyui_dir = Path(config.COMFYUI_MAIN_PATH).parent
        python_path = Path(config.COMFYUI_PYTHON_PATH)
        data_dir = Path(config.COMFYUI_DATA_PATH)
        extra_model_yaml = comfyui_dir / "extra_model_paths.yaml"

        if not Path(config.COMFYUI_MAIN_PATH).exists():
            msg = f"main.py 不存在: {config.COMFYUI_MAIN_PATH}"
            print(f"[image_gen] ERROR: {msg}")
            bus.emit("comfyui_status", {"stage": "failed", "detail": msg})
            return False
        if not python_path.exists():
            msg = f"Python 不存在: {python_path}"
            print(f"[image_gen] ERROR: {msg}")
            bus.emit("comfyui_status", {"stage": "failed", "detail": msg})
            return False

        cmd = [
            str(python_path),
            str(config.COMFYUI_MAIN_PATH),
            "--port", str(config.COMFYUI_PORT),
            "--output-directory", str(data_dir / "output"),
            "--input-directory", str(data_dir / "input"),
            "--user-directory", str(data_dir / "user"),
        ]
        if extra_model_yaml.exists():
            cmd.extend(["--extra-model-paths-config", str(extra_model_yaml)])
            print(f"[image_gen] extra_model_paths: {extra_model_yaml}")
        else:
            print(f"[image_gen] WARNING: extra_model_paths.yaml 不存在: {extra_model_yaml}")

        print(f"[image_gen] 启动 ComfyUI backend...")
        print(f"[image_gen]   python: {cmd[0]}")
        print(f"[image_gen]   main.py: {cmd[1]}")
        print(f"[image_gen]   port: {config.COMFYUI_PORT}")
        print(f"[image_gen]   cwd: {comfyui_dir}")

        env = os.environ.copy()
        env.pop('PYTHONPATH', None)

        log_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.log', delete=False,
            encoding='utf-8', errors='replace',
        )
        log_path = log_file.name
        print(f"[image_gen]   日志: {log_path}")

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=str(comfyui_dir),
                env=env,
                creationflags=creationflags,
            )
        except FileNotFoundError as e:
            msg = f"启动 ComfyUI 失败: {e}"
            print(f"[image_gen] ERROR: {msg}")
            bus.emit("comfyui_status", {"stage": "failed", "detail": msg})
            log_file.close()
            try:
                os.unlink(log_path)
            except Exception:
                pass
            return False
        except Exception as e:
            msg = f"启动 ComfyUI 异常: {e}"
            print(f"[image_gen] ERROR: {msg}")
            bus.emit("comfyui_status", {"stage": "failed", "detail": msg})
            log_file.close()
            try:
                os.unlink(log_path)
            except Exception:
                pass
            return False

        print(f"[image_gen] PID: {self._process.pid}")
        timeout = config.COMFYUI_STARTUP_TIMEOUT
        print(f"[image_gen] 等待 API 就绪 (最多 {timeout}s)...")
        bus.emit("comfyui_status", {"stage": "api_wait", "detail": "等待 ComfyUI API 就绪..."})

        for i in range(timeout):
            ret = self._process.poll()
            if ret is not None:
                log_file.close()
                tail = ""
                try:
                    with open(log_path, encoding='utf-8', errors='replace') as f:
                        tail = f.read()[-500:]
                except Exception:
                    pass
                msg = f"ComfyUI 进程已退出 (code={ret})"
                print(f"[image_gen] ERROR: {msg}")
                if tail.strip():
                    print(f"[image_gen]   {tail}")
                bus.emit("comfyui_status", {"stage": "failed",
                    "detail": msg + ("\n" + tail if tail.strip() else "")})
                try:
                    os.unlink(log_path)
                except Exception:
                    pass
                self._process = None
                return False

            if self._check_api():
                print(f"[image_gen] API 就绪 ({i+1}s)，加载模型中...")
                bus.emit("comfyui_status", {"stage": "models_loading",
                    "detail": "正在加载生图模型 (约 10s)..."})
                time.sleep(10)
                self._ready = True
                print("[image_gen] ComfyUI 就绪")
                bus.emit("comfyui_status", {"stage": "ready",
                    "detail": "ComfyUI 已就绪，可以生成图片"})
                return True

            if i % 5 == 0 and i > 0:
                bus.emit("comfyui_status", {"stage": "api_wait",
                    "detail": f"等待 API 就绪... ({i}s)"})
            time.sleep(1)
            if i % 30 == 29:
                print(f"[image_gen] 仍在等待... ({i+1}s)")

        msg = f"启动超时 ({timeout}s)"
        print(f"[image_gen] ERROR: {msg}")
        bus.emit("comfyui_status", {"stage": "failed", "detail": msg})
        log_file.close()
        self.stop()
        return False

    def stop(self):
        """关闭 ComfyUI 子进程，释放 GPU 显存。"""
        if self._process is None:
            self._ready = False
            return
        if self._process.poll() is not None:
            print("[image_gen] ComfyUI 已自然退出")
            self._process = None
            self._ready = False
            return

        print("[image_gen] 关闭 ComfyUI...")
        try:
            self._process.terminate()
            self._process.wait(timeout=30)
            print("[image_gen] ComfyUI 已关闭")
        except subprocess.TimeoutExpired:
            print("[image_gen] 超时，强制结束...")
            self._process.kill()
            self._process.wait(timeout=10)
        except Exception as e:
            print(f"[image_gen] 关闭异常: {e}")
            try:
                self._process.kill()
            except Exception:
                pass
        self._process = None
        self._ready = False

    def ensure_running(self) -> bool:
        """确保 ComfyUI 正在运行；未运行时尝试启动。"""
        if self._ready and self._check_api():
            return True
        return self.start()

    # ═══ 工作流模板 ═══

    # ── 默认硬编码节点 ID（内置工作流兼容 + 兜底）──
    _FALLBACK_NODE_IDS = {
        "positive_prompt": "6",
        "negative_prompt": "7",
        "sampler": "3",
        "latent": "5",
        "save": "11",
        "unet": "4",
        "clip": "9",
        "vae": "10",
    }

    # ── class_type → 角色映射（按优先级）──
    _CLASS_TYPE_ROLES = [
        (("KSampler",), "sampler"),
        (("EmptyLatentImage", "EmptySD3LatentImage"), "latent"),
        (("SaveImage", "PreviewImage"), "save"),
        (("UNETLoader",), "unet"),
        (("CLIPLoader", "DualCLIPLoader"), "clip"),
        (("VAELoader",), "vae"),
    ]

    def _scan_workflow_nodes(self, workflow: dict) -> dict:
        """扫描工作流 JSON，按 class_type 映射节点角色 -> 节点 ID。

        CLIPTextEncode 有多个：第一个 → positive_prompt，第二个 → negative_prompt。
        """
        nodes = {}
        clip_encodes = []
        errors = []

        for nid, nd in workflow.items():
            if not isinstance(nd, dict):
                continue
            ct = nd.get("class_type", "")
            if not ct:
                continue

            if ct == "CLIPTextEncode":
                clip_encodes.append(nid)
                continue

            for types, role in self._CLASS_TYPE_ROLES:
                if ct in types:
                    nodes[role] = nid
                    break

        if len(clip_encodes) >= 2:
            nodes["positive_prompt"] = clip_encodes[0]
            nodes["negative_prompt"] = clip_encodes[1]
        elif len(clip_encodes) == 1:
            nodes["positive_prompt"] = clip_encodes[0]
            errors.append("仅检测到1个CLIPTextEncode节点，无negative prompt节点")
        else:
            errors.append("未检测到CLIPTextEncode节点")

        # 检查缺失的关键节点
        for role in ("positive_prompt", "sampler", "latent", "save"):
            if role not in nodes:
                errors.append(f"未检测到{role}节点")

        self._scan_errors = errors
        return nodes

    def _load_workflow(self) -> dict:
        """加载工作流模板，自动扫描节点 ID 映射。

        优先级：用户自定义文件 > 内置模板。
        每次调用重新扫描（开销极小，避免缓存失效问题）。
        """
        workflow_path = config.get_workflow_path()
        custom = bool(config.WORKFLOW_PATH and Path(config.WORKFLOW_PATH).exists())

        if not custom:
            # 使用内置模板（带缓存深拷贝）
            if self._workflow_template is not None:
                workflow = json.loads(json.dumps(self._workflow_template))
            else:
                if not workflow_path.exists():
                    raise FileNotFoundError(f"工作流文件不存在: {workflow_path}")
                with open(workflow_path, encoding="utf-8") as f:
                    self._workflow_template = json.load(f)
                workflow = json.loads(json.dumps(self._workflow_template))
        else:
            if not workflow_path.exists():
                raise FileNotFoundError(f"自定义工作流不存在: {workflow_path}")
            with open(workflow_path, encoding="utf-8") as f:
                workflow = json.load(f)
            print(f"[image_gen] 使用自定义工作流: {workflow_path}")

        self._node_map = self._scan_workflow_nodes(workflow)
        if self._scan_errors:
            for err in self._scan_errors:
                print(f"[image_gen] 工作流扫描: {err}")

        # 打印检测结果
        for role, nid in sorted(self._node_map.items()):
            print(f"[image_gen]   节点 {role} → #{nid}")

        return workflow

    def _resolve_node(self, key: str, workflow: dict) -> str:
        """解析节点 ID：手动覆盖 > 自动扫描 > 硬编码兜底。
        同时校验节点是否存在于 workflow 中。
        """
        overrides = getattr(config, 'WORKFLOW_NODE_OVERRIDES', {}) or {}
        if key in overrides:
            nid = overrides[key]
            if nid in workflow:
                return nid
            print(f"[image_gen] 手动覆盖节点 #{nid}({key}) 不在工作流中，回退")

        nid = self._node_map.get(key)
        if nid and nid in workflow:
            return nid

        nid = self._FALLBACK_NODE_IDS.get(key, "")
        if nid and nid in workflow:
            return nid

        return ""

    def _inject_workflow(self, prompt: str, prefix: str, seed: int = None) -> dict:
        """向工作流模板注入 prompt / seed / 尺寸 / 模型等参数。"""
        workflow = self._load_workflow()

        if seed is None:
            seed = random.randint(1, 2 ** 31 - 1)

        pos_node = self._resolve_node("positive_prompt", workflow)
        neg_node = self._resolve_node("negative_prompt", workflow)
        sampler_node = self._resolve_node("sampler", workflow)
        latent_node = self._resolve_node("latent", workflow)
        save_node = self._resolve_node("save", workflow)
        unet_node = self._resolve_node("unet", workflow)
        clip_node = self._resolve_node("clip", workflow)
        vae_node = self._resolve_node("vae", workflow)

        if pos_node:
            workflow[pos_node]["inputs"]["text"] = prompt

        if neg_node:
            workflow[neg_node]["inputs"]["text"] = (
                "lowres, bad anatomy, bad hands, text, error, missing fingers, "
                "extra digit, fewer digits, cropped, worst quality, low quality, "
                "normal quality, jpeg artifacts, signature, watermark, username, blurry"
            )

        if latent_node:
            workflow[latent_node]["inputs"]["width"] = config.IMAGE_GEN_WIDTH
            workflow[latent_node]["inputs"]["height"] = config.IMAGE_GEN_HEIGHT

        if sampler_node:
            workflow[sampler_node]["inputs"]["seed"] = seed
            workflow[sampler_node]["inputs"]["steps"] = config.IMAGE_GEN_STEPS
            workflow[sampler_node]["inputs"]["cfg"] = config.IMAGE_GEN_CFG

        if save_node:
            workflow[save_node]["inputs"]["filename_prefix"] = prefix

        if unet_node:
            workflow[unet_node]["inputs"]["unet_name"] = config.COMFY_MODEL_DIFFUSION
        if clip_node:
            workflow[clip_node]["inputs"]["clip_name"] = config.COMFY_MODEL_CLIP
        if vae_node:
            workflow[vae_node]["inputs"]["vae_name"] = config.COMFY_MODEL_VAE

        return workflow

    # ═══ ComfyUI API ═══

    def _submit_workflow(self, workflow: dict) -> str:
        """提交工作流，返回 prompt_id。"""
        url = f"http://{config.COMFYUI_HOST}:{config.COMFYUI_PORT}/prompt"
        payload = json.dumps({"prompt": workflow}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors='replace')[:1000]
            raise RuntimeError(f"ComfyUI HTTP {e.code}: {body}")

        if result.get("node_errors"):
            for node_id, err in result["node_errors"].items():
                for e in err.get("errors", []):
                    print(f"[image_gen] 节点 {node_id} 错误: {e.get('message', str(e))}")
            raise RuntimeError("工作流包含节点错误")

        pid = result.get("prompt_id")
        if not pid:
            raise RuntimeError(f"ComfyUI 未返回 prompt_id: {result}")
        return pid

    def _wait_for_result(self, prompt_id: str, timeout: int = None) -> list:
        """轮询等待生成完成，返回输出图片路径列表。"""
        if timeout is None:
            timeout = config.COMFYUI_GEN_TIMEOUT
        data_dir = Path(config.COMFYUI_DATA_PATH)
        start = time.time()
        last_tick = 0

        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise TimeoutError(f"生成超时 ({timeout}s)")

            try:
                req = urllib.request.Request(
                    f"http://{config.COMFYUI_HOST}:{config.COMFYUI_PORT}/history/{prompt_id}"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    history = json.loads(resp.read())
            except Exception:
                time.sleep(2)
                continue

            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                images = []
                for node_id, node_output in outputs.items():
                    if "images" in node_output:
                        for img in node_output["images"]:
                            fname = img["filename"]
                            subfolder = img.get("subfolder", "")
                            if subfolder:
                                img_path = data_dir / "output" / subfolder / fname
                            else:
                                img_path = data_dir / "output" / fname
                            images.append(img_path)
                if images:
                    return images

            if int(elapsed) % 10 == 0 and int(elapsed) != last_tick:
                print(f"[image_gen] 生成中... ({int(elapsed)}s)")
                last_tick = int(elapsed)

            time.sleep(3)

    # ═══ 提示词构建 ═══

    def _extract_appearance(self, c: dict) -> str:
        system_prompt = c.get("system_prompt", "")
        if system_prompt:
            m = re.search(r'外在形象[：:]\s*(.+?)(?:\n|。|$)', system_prompt)
            if m:
                return m.group(1).strip()[:120]
        return c.get("description", "")

    def _build_auto_prompt(self) -> tuple:
        """根据当前场景 + 活跃角色外貌衣着 + 最近剧情对话，调用 LLM 生成英文生图提示词。"""
        scene = self.app.current_scene or {}
        mood = scene.get("mood", "")
        time_label = scene.get("time", "")
        location = scene.get("location", "")
        scene_desc = scene.get("scene", "")

        # 获取最近剧情消息（排除导演/事件/NPC/图片）
        history = self.app.history_snapshot()
        recent_msgs = [m for m in history[-12:]
                       if m.get("type") not in ("director", "random_event", "random_npc", "image")]

        # 识别场景中活跃的角色（最近10条消息中发言或被提及的角色）
        active_chars = set()
        for m in recent_msgs[-10:]:
            name = m.get("name", "")
            if name and name in self.app.characters:
                active_chars.add(name)
            text = m.get("text", "")
            for n in self.app._get_effective_order():
                dname = self.app.characters.get(n, {}).get("display_name", "")
                if (dname and dname in text) or n in text:
                    active_chars.add(n)

        # 兜底：至少包含最近发言的 1 位角色
        if not active_chars and recent_msgs:
            last = recent_msgs[-1]
            name = last.get("name", "")
            if name and name in self.app.characters:
                active_chars.add(name)

        # 收集活跃角色的外貌衣着信息
        char_lines = []
        for name in active_chars:
            c = self.app.characters.get(name, {})
            dname = c.get("display_name", name)
            appearance = self._extract_appearance(c)
            pers = c.get("personality", "")
            line = f"- {dname}: {appearance}"
            if pers:
                line += f"。性格: {pers}"
            char_lines.append(line)

        # 最近剧情对话（含完整文本，用于抓取画面感）
        recent_lines = []
        for m in recent_msgs[-8:]:
            dname = m.get("display_name", m.get("name", ""))
            text = m.get("text", "")[:200]
            recent_lines.append(f"{dname}: {text}")

        world_config = self.app._profile_config.get("world", {})
        world_setting = world_config.get("setting", "")

        char_section = "\n".join(char_lines) if char_lines else "(暂无活跃角色)"
        dialogue_section = "\n".join(recent_lines) if recent_lines else "(暂无对话)"

        prompt = (
            "You are an expert image generation prompt writer for anime illustrations. "
            "Your task is to capture the CURRENT MOMENT from the story below as a single "
            "illustration that reflects what's actually happening right now.\n\n"
            "STYLE: Japanese anime style (アニメ). Studio Ghibli / Makoto Shinkai aesthetic. "
            "Vibrant colors, clean linework, cinematic lighting.\n\n"
            "CRITICAL: The image must match the present moment in the story, "
            "not just a generic scene. Use the recent dialogue and actions to determine "
            "what the characters are actually doing right now.\n\n"
            "Requirements:\n"
            "- Write in English, natural paragraph style (80-140 words)\n"
            "- Focus on 1-3 key characters who are active in the scene — do NOT list every character\n"
            "- Describe the specific action/moment from the recent dialogue, not a generic pose\n"
            "- Keep composition clean: one clear focal point, avoid cramming too many elements\n"
            "- Include: composition angle, character position/pose/expression, key clothing, "
            "lighting/mood, essential environment\n\n"
            "Output format — exactly TWO lines, nothing else:\n"
            "Line 1: The English prompt\n"
            "Line 2: SUMMARY: brief Chinese description of the scene (10-25 chars)\n\n"
            f"【World Setting】\n{world_setting}\n\n"
            f"【Current Scene】\n{time_label}. Location: {location}. Mood: {mood}. {scene_desc}\n\n"
            f"【Active Characters (appearance & clothing)】\n{char_section}\n\n"
            f"【Recent Story Actions】\n{dialogue_section}\n"
        )

        try:
            result = call_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.75,
                max_tokens=400,
                timeout=30.0,
            )
            result = result.strip()
            # 解析 SUMMARY: 行
            summary = ""
            image_prompt = result
            summary_match = re.search(r'SUMMARY:\s*(.+?)$', result, re.MULTILINE)
            if summary_match:
                summary = summary_match.group(1).strip()
                image_prompt = re.sub(r'\n?\s*SUMMARY:.*$', '', result, flags=re.MULTILINE).strip()
            # 检查 LLM 是否返回了有效内容（排除只有 SUMMARY 或只有质量标签的情况）
            _bare = image_prompt.strip().rstrip(",").strip()
            _tag_str = "masterpiece, best quality, Japanese anime style"
            if not _bare or _bare.lower() == _tag_str.lower():
                raise ValueError("LLM returned empty or tag-only prompt")
            # 添加动漫质量标签
            if "masterpiece" not in image_prompt.lower():
                image_prompt = f"{_tag_str}, {image_prompt}"
            return image_prompt, summary
        except Exception as e:
            print(f"[image_gen] 自动提示词 LLM 失败: {e}")
            return self._build_fallback_prompt(scene, char_lines, recent_lines, active_chars)

    def _build_fallback_prompt(self, scene: dict, char_lines: list,
                                recent_lines: list, active_chars: set) -> tuple:
        """LLM 生成失败时，直接拼接场景 + 角色外观 + 最近对话为生图 prompt。"""
        mood = scene.get("mood", "")
        time_label = scene.get("time", "")
        location = scene.get("location", "")
        scene_desc = scene.get("scene", "")

        parts = ["masterpiece, best quality, Japanese anime style"]

        if time_label or location or mood:
            setting = ", ".join(filter(None, [time_label, location, f"{mood} atmosphere"]))
            parts.append(setting)

        if scene_desc:
            parts.append(scene_desc[:200])

        if active_chars:
            char_descs = []
            for name in active_chars:
                c = self.app.characters.get(name, {})
                dname = c.get("display_name", name)
                app = self._extract_appearance(c)
                if app:
                    char_descs.append(f"{dname}: {app[:80]}")
            if char_descs:
                parts.append("characters: " + "; ".join(char_descs))

        if recent_lines:
            latest = recent_lines[-1] if recent_lines else ""
            if latest:
                parts.append("action: " + latest[:120])

        return ", ".join(parts), ""

    # ═══ 公开接口 ═══

    def generate(self, prompt: str, chat_images_dir: Path, source: str = "auto",
                 character: str = None) -> Optional[dict]:
        """同步生成一张图片。

        Args:
            prompt: 生图提示词（auto 模式由调用方先调 _build_auto_prompt 获取）
            chat_images_dir: chat 的 images/ 目录，输出文件存放于此
            source: "auto" | "char"
            character: 角色名（仅 source="char" 时有效）

        Returns:
            image_info dict: {image_path, thumb_path, prompt, source,
                              character, display_name}
            失败返回 None。
        """
        if not self._ready:
            print("[image_gen] ComfyUI 未就绪")
            return None

        # 为所有 prompt 添加动漫质量标签（角色请求的 prompt 可能不含）
        if "masterpiece" not in prompt.lower():
            prompt = f"masterpiece, best quality, Japanese anime style, {prompt}"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        if source == "char" and character:
            dname = self.app.characters.get(character, {}).get("display_name", character)
            prefix = f"char_{dname}_{ts}"
            image_display_name = f"{dname} 的插画"
        else:
            prefix = f"auto_{ts}"
            dname = ""
            image_display_name = "场景插图"

        print(f"[image_gen] 生成 {source}: prefix={prefix}")
        print(f"[image_gen]   prompt: {prompt[:120]}...")

        try:
            workflow = self._inject_workflow(prompt, prefix)
            pid = self._submit_workflow(workflow)
            print(f"[image_gen]   prompt_id={pid}")
        except Exception as e:
            print(f"[image_gen] 提交失败: {e}")
            return None

        try:
            images = self._wait_for_result(pid)
        except TimeoutError:
            print(f"[image_gen] 生成超时")
            return None
        except Exception as e:
            print(f"[image_gen] 等待结果失败: {e}")
            return None

        if not images:
            print("[image_gen] 未收到输出图片")
            return None

        src = images[0]
        if not src.exists():
            print(f"[image_gen] 输出文件不存在: {src}")
            return None

        chat_images_dir.mkdir(parents=True, exist_ok=True)

        fname = f"{prefix}.png"
        thumb_fname = f"{prefix}_thumb.jpg"
        dest = chat_images_dir / fname
        thumb_dest = chat_images_dir / thumb_fname

        try:
            with open(src, "rb") as fin, open(dest, "wb") as fout:
                fout.write(fin.read())
        except Exception as e:
            print(f"[image_gen] 复制原图失败: {e}")
            return None

        try:
            self._create_thumbnail(src, thumb_dest, max_size=600)
        except Exception as e:
            print(f"[image_gen] 缩略图失败: {e}")

        size_kb = dest.stat().st_size / 1024
        print(f"[image_gen] 完成: {fname} ({size_kb:.0f} KB)")

        return {
            "image_path": fname,
            "thumb_path": thumb_fname,
            "prompt": prompt,
            "source": source,
            "character": character,
            "display_name": image_display_name,
        }

    # ═══ 文件工具 ═══

    def _create_thumbnail(self, src_path: Path, thumb_path: Path, max_size: int = 600):
        """使用 Pillow 创建 JPEG 缩略图。"""
        img = Image.open(str(src_path))
        img = img.convert("RGB")
        w, h = img.size
        if w > max_size or h > max_size:
            ratio = max_size / max(w, h)
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        img.save(str(thumb_path), "JPEG", quality=85)
