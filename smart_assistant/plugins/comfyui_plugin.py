"""Local ComfyUI bridge for image and video workflow generation."""
from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


def _base_url() -> str:
    import brain
    return str(brain.load_config().get("comfyui_url", "http://127.0.0.1:8188")).rstrip("/")


def _valid_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return False
    if parsed.scheme == "https" and parsed.netloc:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _request(path: str, payload: dict | None = None, timeout: int = 20):
    url = _base_url() + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"} if data else {},
                                     method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _cmd_set_url(ctx):
    if len(ctx.args) != 1 or not _valid_url(ctx.args[0]):
        return "usage: comfy_set_url <https-url|http://localhost:port>"
    import brain
    cfg = brain.load_config()
    cfg["comfyui_url"] = ctx.args[0].rstrip("/")
    brain.save_config(cfg)
    return f"✅ ComfyUI endpoint saved: {cfg['comfyui_url']}"


def _cmd_status(ctx):
    try:
        stats = _request("/system_stats")
        queue = _request("/queue")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return f"❌ ComfyUI is unavailable at {_base_url()}: {exc}"
    devices = stats.get("devices", [])
    names = ", ".join(str(d.get("name", "device")) for d in devices) or "unknown device"
    running = len(queue.get("queue_running", []))
    pending = len(queue.get("queue_pending", []))
    return f"✅ ComfyUI ready — {names}; queue: {running} running, {pending} pending"


def _cmd_queue(ctx):
    if len(ctx.args) != 1:
        return "usage: comfy_queue <workflow-api.json>"
    path = Path(ctx.args[0]).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".json":
        return "❌ choose an existing JSON workflow exported in API format"
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict) or not workflow:
            raise ValueError("workflow must be a non-empty object")
        result = _request("/prompt", {"prompt": workflow}, timeout=60)
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        return f"❌ could not queue the workflow: {exc}"
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        return "❌ ComfyUI rejected the workflow: " + json.dumps(result, ensure_ascii=False)[:1200]
    return f"✅ workflow queued — prompt_id: {prompt_id}"


def _cmd_history(ctx):
    if len(ctx.args) != 1:
        return "usage: comfy_history <prompt_id>"
    prompt_id = urllib.parse.quote(ctx.args[0], safe="")
    try:
        result = _request(f"/history/{prompt_id}")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return f"❌ could not read ComfyUI history: {exc}"
    return json.dumps(result, ensure_ascii=False, indent=2)[:12000]


def register(engine):
    engine.registry.register("comfy_set_url", _cmd_set_url, "comfy_set_url <url> — configure local or HTTPS ComfyUI")
    engine.registry.register("comfy_status", _cmd_status, "comfy_status — GPU and queue health")
    engine.registry.register("comfy_queue", _cmd_queue, "comfy_queue <workflow-api.json> — run a Wan/video/image workflow")
    engine.registry.register("comfy_history", _cmd_history, "comfy_history <prompt_id> — inspect workflow outputs")
