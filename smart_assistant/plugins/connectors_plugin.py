"""
connectors_plugin.py — MCP Connectors: يوصل المساعد بأي MCP server خارجي،
بنفس بروتوكول الـ Connectors المستخدم في Claude / Claude Desktop
(Model Context Protocol — بروتوكول مفتوح المصدر من Anthropic، مجاني
بالكامل). الإعداد في connectors.json بنفس شكل ملف إعداد Claude Desktop،
وأي MCP server محلي/مجاني (filesystem, git, fetch, sqlite...) بيشتغل من
غير أي تكلفة.

كل أداة (tool) في السيرفر المتصل بتتسجل كأمر في المحرك باسم
"<connector>.<tool>"، وباخد args كـ JSON واحد (زي: fs.read_file
'{"path": "/tmp/x"}').
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import pathlib
import sys
import threading


def _config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "connectors.json"


class ConnectorManager:
    """
    بيدير كل جلسات الـ MCP (async بطبيعتها) على event loop مستقل شغال
    في Thread واحد، عشان ميصطدمش مع الـ Command Engine اللي شغال sync.
    """

    def __init__(self, engine):
        self.engine = engine
        self.servers: dict[str, dict] = {}  # name -> {"status": str, "tools": [str, ...]}
        self._sessions: dict[str, object] = {}
        self._stacks: dict[str, contextlib.AsyncExitStack] = {}
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._loop_thread.start()

    def _run(self, coro, timeout=60):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def shutdown(self):
        """يقفل كل جلسات MCP المتصلة، ويوقف event loop thread بتاع
        المدير ده بأمان. لازم تتنادى على أي مدير قديم قبل ما نستبدله
        بواحد جديد — core_engine.load_plugins() بينادي register() لكل
        الإضافات (حتى المحمّلة قبل كده) في كل reload_plugins، فمن غير
        shutdown صريح كان كل reload بيسرّب thread + event loop + أي
        جلسات MCP متصلة قديمة بلا حدود (المدير القديم كان بيتنسى
        وبيفضل شغال في الخلفية من غير أي إشارة)."""
        for name in list(self._stacks):
            self.disconnect(name)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=5)

    def load_config(self) -> dict:
        path = _config_path()
        if not path.exists():
            try:
                path.write_text(json.dumps({"mcpServers": {}}, indent=2), encoding="utf-8")
            except OSError:
                pass
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data.get("mcpServers", {})

    # ── connect / disconnect ────────────────────────────────────────────
    def connect(self, name: str):
        config = self.load_config()
        if name not in config:
            self.engine._log(f"❌ connector '{name}' غير موجود في connectors.json", "error")
            return
        if self.servers.get(name, {}).get("status") in ("connected", "connecting"):
            return
        self.servers[name] = {"status": "connecting", "tools": []}
        threading.Thread(target=self._connect_blocking, args=(name, config[name]), daemon=True).start()

    def _connect_blocking(self, name, cfg):
        try:
            self._run(self._async_connect(name, cfg), timeout=90)
        except Exception as e:
            self.servers[name] = {"status": f"error: {e}", "tools": []}
            self.engine._log(f"❌ connector '{name}' فشل الاتصال: {e}", "error")

    async def _async_connect(self, name, cfg):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if "command" not in cfg:
            raise ValueError(f"connectors.json['{name}'] ناقصه 'command'")

        stack = contextlib.AsyncExitStack()
        params = StdioServerParameters(
            command=cfg["command"], args=cfg.get("args", []), env=cfg.get("env"),
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools_result = await session.list_tools()

        self._sessions[name] = session
        self._stacks[name] = stack

        tool_names = []
        for tool in tools_result.tools:
            self._register_tool_command(name, tool.name, tool.description or "")
            tool_names.append(tool.name)
        self.servers[name] = {"status": "connected", "tools": tool_names}
        self.engine._log(
            f"🔌 connector '{name}' متصل — {len(tool_names)} أداة: {', '.join(tool_names)}", "ok"
        )

    def disconnect(self, name: str):
        stack = self._stacks.pop(name, None)
        self._sessions.pop(name, None)
        if stack is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(stack.aclose(), self._loop)
                future.result(timeout=10)
            except Exception:
                pass
        self.servers[name] = {"status": "disconnected", "tools": []}

    # ── tool invocation ─────────────────────────────────────────────────
    def _register_tool_command(self, server_name: str, tool_name: str, description: str):
        command_name = f"{server_name}.{tool_name}"

        def handler(ctx):
            # ملحوظة: مبنعتمدش على ctx.args هنا لأنها متجهزة عن طريق
            # shlex.split اللي بيبلع علامات التنصيص جوه الـ JSON (زي
            # {"a": 1})، فبناخد النص الخام (ctx.raw) ونشيل اسم الأمر بس.
            head_and_rest = ctx.raw.split(maxsplit=1)
            raw_json = head_and_rest[1].strip() if len(head_and_rest) > 1 else ""
            try:
                arguments = json.loads(raw_json) if raw_json else {}
            except json.JSONDecodeError as e:
                return f"usage: {command_name} '<json arguments>'  (JSON error: {e})"
            try:
                result = self._run(self._async_call(server_name, tool_name, arguments))
            except Exception as e:
                return f"❌ فشل تنفيذ الأداة: {e}"
            return self._format_result(result)

        self.engine.registry.register(
            command_name, handler, f"[MCP:{server_name}] {description}"[:150]
        )

    async def _async_call(self, server_name: str, tool_name: str, arguments: dict):
        session = self._sessions.get(server_name)
        if session is None:
            raise RuntimeError(f"connector '{server_name}' مش متصل")
        return await session.call_tool(tool_name, arguments)

    @staticmethod
    def _format_result(result) -> str:
        parts = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
        out = "\n".join(parts) if parts else str(result)
        return out[:4000]

    def status_text(self) -> str:
        config = self.load_config()
        if not config:
            return (
                "مفيش أي connector متظبط. عدّل connectors.json (زي connectors.example.json) "
                "وشغّل: connectors connect <name>"
            )
        lines = []
        for name in config:
            info = self.servers.get(name, {"status": "not connected", "tools": []})
            extra = f" ({len(info['tools'])} tools)" if info["tools"] else ""
            lines.append(f"{name}: {info['status']}{extra}")
        return "\n".join(lines)


def register(engine):
    try:
        import mcp  # noqa: F401
    except ImportError:
        def _cmd_missing(ctx):
            return "❌ باكدج mcp مش متثبت — ثبّته بـ: pip install mcp"
        engine.registry.register("connectors", _cmd_missing, "MCP connectors (needs: pip install mcp)")
        return

    existing_manager = getattr(engine, "connector_manager", None)
    if existing_manager is not None:
        existing_manager.shutdown()

    manager = ConnectorManager(engine)
    engine.connector_manager = manager  # متاح لأي إضافة تانية لو حابة تستخدمه

    def _cmd_connectors(ctx):
        if len(ctx.args) >= 2 and ctx.args[0] == "connect":
            manager.connect(ctx.args[1])
            return f"⏳ بحاول أتصل بـ {ctx.args[1]}... (تابع اللوج)"
        if len(ctx.args) >= 2 and ctx.args[0] == "disconnect":
            manager.disconnect(ctx.args[1])
            return f"🔌 اتقطع الاتصال مع {ctx.args[1]}"
        return manager.status_text()

    engine.registry.register(
        "connectors", _cmd_connectors,
        "connectors | connectors connect <name> | connectors disconnect <name>",
    )

    # اتصال تلقائي (في الخلفية، من غير ما يوقف تحميل باقي الإضافات) بكل
    # الـ connectors المعرّفة في connectors.json
    for name in manager.load_config():
        manager.connect(name)
