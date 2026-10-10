"""Production MCP connector host for Jarvis.

Supports local stdio servers and remote Streamable HTTP servers. Secrets are
referenced from environment variables instead of being copied into the config.
Every discovered MCP tool becomes ``<connector>.<tool>`` in Jarvis.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import re
import shutil
import sys
import threading
import time
from urllib.parse import urlparse


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_TOOL_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_ENV_RE = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")
_MAX_RESULT_CHARS = 20_000

CONNECTOR_CATALOG = {
    "github": {
        "description": "Official GitHub remote MCP (repositories, issues, PRs, Actions)",
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {"Authorization": "Bearer ${env:GITHUB_PERSONAL_ACCESS_TOKEN}"},
        "requires": ["environment variable GITHUB_PERSONAL_ACCESS_TOKEN"],
        "autoConnect": False,
    },
    "canva": {
        "description": "Official Canva AI Connector (designs, assets, exports, comments)",
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote@latest", "https://mcp.canva.com/mcp"],
        "requires": ["Node.js 22.16+", "eligible Canva account and browser OAuth"],
        "autoConnect": False,
    },
    "gmail": {
        "description": "Google Workspace community MCP, limited to Gmail tools",
        "type": "stdio",
        "command": "uvx",
        "args": ["workspace-mcp", "--tools", "gmail"],
        "env": {
            "GOOGLE_OAUTH_CLIENT_ID": "${env:GOOGLE_OAUTH_CLIENT_ID}",
            "GOOGLE_OAUTH_CLIENT_SECRET": "${env:GOOGLE_OAUTH_CLIENT_SECRET}",
        },
        "requires": ["uv", "Google Desktop OAuth client with Gmail API enabled"],
        "trust": "community: https://github.com/taylorwilsdon/google_workspace_mcp",
        "autoConnect": False,
    },
}


def _config_path() -> pathlib.Path:
    base = pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else pathlib.Path(__file__).resolve().parent.parent
    return base / "connectors.json"


def _resolve_env(value):
    """Resolve explicit ${env:NAME} placeholders and reject missing secrets."""
    if isinstance(value, str):
        missing: list[str] = []

        def replace(match):
            name = match.group(1)
            resolved = os.environ.get(name)
            if resolved is None:
                missing.append(name)
                return ""
            return resolved

        resolved = _ENV_RE.sub(replace, value)
        if missing:
            raise ValueError("missing environment variable(s): " + ", ".join(sorted(set(missing))))
        return resolved
    if isinstance(value, dict):
        return {str(k): _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def _validate_server(name: str, cfg: dict) -> dict:
    if not _NAME_RE.fullmatch(name):
        raise ValueError("connector name must use letters, numbers, '-' or '_' (max 64)")
    if not isinstance(cfg, dict):
        raise ValueError(f"connector '{name}' must be an object")
    transport = cfg.get("type") or ("stdio" if "command" in cfg else "http" if "url" in cfg else "")
    if transport == "stdio":
        if not isinstance(cfg.get("command"), str) or not cfg["command"].strip():
            raise ValueError(f"connectors.json['{name}'] is missing 'command'")
        if not isinstance(cfg.get("args", []), list) or not all(isinstance(v, str) for v in cfg.get("args", [])):
            raise ValueError(f"connectors.json['{name}'].args must be a string list")
    elif transport in {"http", "streamable-http"}:
        url = cfg.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError(f"connectors.json['{name}'] needs a valid HTTP URL")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("remote MCP endpoints must use HTTPS")
        if not isinstance(cfg.get("headers", {}), dict):
            raise ValueError(f"connectors.json['{name}'].headers must be an object")
    else:
        raise ValueError(f"connector '{name}' type must be stdio or http")
    return {**cfg, "type": "http" if transport == "streamable-http" else transport}


class ConnectorManager:
    """Owns MCP sessions on one dedicated asyncio loop."""

    def __init__(self, engine):
        self.engine = engine
        self.servers: dict[str, dict] = {}
        self._sessions: dict[str, object] = {}
        self._stacks: dict[str, contextlib.AsyncExitStack] = {}
        self._tool_schemas: dict[str, dict[str, dict]] = {}
        self._registered_commands: dict[str, set[str]] = {}
        self._lock = threading.RLock()
        self._config_error = ""
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, name="nezuko-connectors", daemon=True,
        )
        self._loop_thread.start()

    def _manager_lock(self):
        lock = getattr(self, "_lock", None)
        if lock is None:
            lock = self._lock = threading.RLock()
        return lock

    def _run(self, coro, timeout=60):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def shutdown(self):
        if getattr(self, "_closed", False):
            return
        self._closed = True
        for name in list(self._stacks):
            self.disconnect(name)
        if getattr(self, "_loop", None) is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if getattr(self, "_loop_thread", None) is not None:
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
            if not isinstance(data, dict):
                raise ValueError("connector configuration must be an object")
            servers = data.get("mcpServers", {})
            if not isinstance(servers, dict):
                raise ValueError("mcpServers must be an object")
            self._config_error = ""
            return servers
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._config_error = str(exc)
            return {}

    def save_config(self, servers: dict) -> None:
        for name, cfg in servers.items():
            _validate_server(name, cfg)
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"mcpServers": servers}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def add_preset(self, preset: str, name: str | None = None) -> str:
        if preset not in CONNECTOR_CATALOG:
            raise ValueError(f"unknown preset: {preset}")
        target = name or preset
        _validate_server(target, CONNECTOR_CATALOG[preset])
        servers = self.load_config()
        if target in servers:
            raise ValueError(f"connector '{target}' already exists")
        servers[target] = {k: v for k, v in CONNECTOR_CATALOG[preset].items() if k != "description"}
        self.save_config(servers)
        return target

    def add_http(self, name: str, url: str) -> None:
        servers = self.load_config()
        if name in servers:
            raise ValueError(f"connector '{name}' already exists")
        servers[name] = _validate_server(name, {"type": "http", "url": url, "autoConnect": False})
        self.save_config(servers)

    def add_stdio(self, name: str, command: str, args: list[str]) -> None:
        servers = self.load_config()
        if name in servers:
            raise ValueError(f"connector '{name}' already exists")
        servers[name] = _validate_server(
            name, {"type": "stdio", "command": command, "args": args, "autoConnect": False},
        )
        self.save_config(servers)

    def remove(self, name: str) -> None:
        servers = self.load_config()
        if name not in servers:
            raise ValueError(f"connector '{name}' is not configured")
        self.disconnect(name)
        del servers[name]
        self.save_config(servers)

    def connect(self, name: str):
        if getattr(self, "_closed", False):
            self.engine._log(f"❌ connector manager is shut down; reload plugins first", "error")
            return False
        config = self.load_config()
        if name not in config:
            self.engine._log(f"❌ connector '{name}' is not in connectors.json", "error")
            return False
        try:
            cfg = _validate_server(name, config[name])
            _resolve_env(cfg.get("env", {}))
            _resolve_env(cfg.get("headers", {}))
        except ValueError as exc:
            self.servers[name] = {"status": f"error: {exc}", "tools": [], "latency_ms": None}
            self.engine._log(f"❌ connector '{name}' configuration: {exc}", "error")
            return False
        with self._manager_lock():
            if self.servers.get(name, {}).get("status") in ("connected", "connecting"):
                return False
            self.servers[name] = {"status": "connecting", "tools": [], "latency_ms": None}
        threading.Thread(
            target=self._connect_blocking, args=(name, cfg),
            name=f"nezuko-connector-{name}", daemon=True,
        ).start()
        return True

    def _connect_blocking(self, name, cfg):
        started = time.perf_counter()
        try:
            self._run(self._async_connect(name, cfg), timeout=int(cfg.get("connectTimeout", 90)))
            if self.servers.get(name, {}).get("status") == "connected":
                self.servers[name]["latency_ms"] = round((time.perf_counter() - started) * 1000)
        except Exception as exc:
            self.servers[name] = {
                "status": f"error: {type(exc).__name__}: {exc}", "tools": [],
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
            self.engine._log(f"❌ connector '{name}' failed to connect: {exc}", "error")

    async def _async_connect(self, name, cfg):
        from mcp import ClientSession, StdioServerParameters

        cfg = _validate_server(name, cfg)
        stack = contextlib.AsyncExitStack()
        try:
            if cfg["type"] == "stdio":
                from mcp.client.stdio import stdio_client
                child_env = dict(os.environ)
                child_env.update(_resolve_env(cfg.get("env", {})))
                params = StdioServerParameters(
                    command=cfg["command"], args=cfg.get("args", []), env=child_env,
                )
                streams = await stack.enter_async_context(stdio_client(params))
            else:
                from mcp.client.streamable_http import streamable_http_client
                headers = _resolve_env(cfg.get("headers", {}))
                if headers:
                    try:
                        import httpx2 as httpx_client
                    except ImportError:
                        import httpx as httpx_client
                    client = await stack.enter_async_context(
                        httpx_client.AsyncClient(headers=headers, timeout=float(cfg.get("requestTimeout", 60)))
                    )
                    streams = await stack.enter_async_context(
                        streamable_http_client(cfg["url"], http_client=client)
                    )
                else:
                    streams = await stack.enter_async_context(streamable_http_client(cfg["url"]))

            read, write = streams[0], streams[1]
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            tools_result = await session.list_tools()
        except Exception:
            await stack.aclose()
            raise

        safe_tools = [tool for tool in tools_result.tools if _TOOL_RE.fullmatch(tool.name)]
        rejected = [tool.name for tool in tools_result.tools if not _TOOL_RE.fullmatch(tool.name)]
        if rejected:
            self.engine._log(
                f"⚠ connector '{name}' exposed invalid tool names; ignored {len(rejected)}", "warn",
            )
        command_names = [f"{name}.{tool.name}" for tool in safe_tools]
        collisions = [command for command in command_names if self.engine.registry.get(command) is not None]
        if collisions:
            await stack.aclose()
            raise ValueError("connector tool command collision: " + ", ".join(collisions))

        self._sessions[name] = session
        self._stacks[name] = stack
        tools, schemas = [], {}
        for tool in safe_tools:
            self._register_tool_command(name, tool.name, tool.description or "")
            tools.append(tool.name)
            schemas[tool.name] = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", {}) or {}
        self._tool_schemas[name] = schemas
        self.servers[name] = {"status": "connected", "tools": tools, "latency_ms": None}
        self.engine._log(f"🔌 connector '{name}' connected — {len(tools)} tools", "ok")

    def disconnect(self, name: str):
        stack = self._stacks.pop(name, None)
        self._sessions.pop(name, None)
        getattr(self, "_tool_schemas", {}).pop(name, None)
        for command_name in getattr(self, "_registered_commands", {}).pop(name, set()):
            self.engine.registry.unregister(command_name)
            getattr(self.engine, "_plugin_commands", set()).discard(command_name)
        if stack is not None and getattr(self, "_loop", None) is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(stack.aclose(), self._loop)
                future.result(timeout=10)
            except Exception:
                pass
        self.servers[name] = {"status": "disconnected", "tools": [], "latency_ms": None}

    def reconnect(self, name: str):
        self.disconnect(name)
        return self.connect(name)

    def _register_tool_command(self, server_name: str, tool_name: str, description: str):
        if not _TOOL_RE.fullmatch(tool_name):
            raise ValueError(f"invalid MCP tool name: {tool_name!r}")
        command_name = f"{server_name}.{tool_name}"
        existing = self.engine.registry.get(command_name)
        if existing is not None:
            raise ValueError(f"connector tool command collision: {command_name}")

        def handler(ctx):
            head_and_rest = ctx.raw.split(maxsplit=1)
            raw_json = head_and_rest[1].strip() if len(head_and_rest) > 1 else ""
            try:
                arguments = json.loads(raw_json) if raw_json else {}
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be one JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                return f"usage: {command_name} '<json arguments>'  (JSON error: {exc})"
            try:
                result = self._run(self._async_call(server_name, tool_name, arguments), timeout=120)
            except Exception as exc:
                return f"❌ the connector tool failed: {type(exc).__name__}: {exc}"
            return self._format_result(result)

        self.engine.registry.register(command_name, handler, f"[MCP:{server_name}] {description}"[:200])
        registered = getattr(self, "_registered_commands", None)
        if registered is None:
            registered = self._registered_commands = {}
        registered.setdefault(server_name, set()).add(command_name)
        getattr(self.engine, "_plugin_commands", set()).add(command_name)

    async def _async_call(self, server_name: str, tool_name: str, arguments: dict):
        session = self._sessions.get(server_name)
        if session is None:
            raise RuntimeError(f"connector '{server_name}' is not connected")
        return await session.call_tool(tool_name, arguments)

    @staticmethod
    def _format_result(result) -> str:
        parts = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
                continue
            resource = getattr(item, "resource", None)
            if resource is not None:
                parts.append(getattr(resource, "text", None) or str(resource))
        if getattr(result, "isError", False) or getattr(result, "is_error", False):
            parts.insert(0, "❌ MCP tool returned an error")
        structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
        if structured and not parts:
            parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
        out = "\n".join(parts) if parts else str(result)
        if len(out) > _MAX_RESULT_CHARS:
            out = out[:_MAX_RESULT_CHARS] + f"\n… truncated {len(out) - _MAX_RESULT_CHARS} characters"
        return out

    def tools_text(self, name: str) -> str:
        schemas = getattr(self, "_tool_schemas", {}).get(name, {})
        if not schemas:
            return f"no tools discovered for '{name}' — connect it first"
        lines = [f"{name} tools ({len(schemas)}):"]
        for tool, schema in sorted(schemas.items()):
            required = schema.get("required", []) if isinstance(schema, dict) else []
            lines.append(f"  {name}.{tool}" + (f" — required: {', '.join(required)}" if required else ""))
        return "\n".join(lines)

    def doctor_text(self) -> str:
        config = self.load_config()
        lines = ["Connector readiness:"]
        if getattr(self, "_config_error", ""):
            lines.append(f"  ❌ connectors.json: {self._config_error}")
        else:
            lines.append(f"  ✅ connectors.json: {len(config)} configured")
        lines.append(f"  {'✅' if shutil.which('npx') else '❌'} npx (stdio npm servers)")
        lines.append(f"  {'✅' if shutil.which('uvx') else '❌'} uvx (stdio Python servers)")
        for name, raw in sorted(config.items()):
            try:
                cfg = _validate_server(name, raw)
                _resolve_env(cfg.get("env", {}))
                _resolve_env(cfg.get("headers", {}))
                state = self.servers.get(name, {}).get("status", "ready to connect")
                lines.append(f"  ✅ {name}: {cfg['type']}; {state}")
            except ValueError as exc:
                lines.append(f"  ❌ {name}: {exc}")
        return "\n".join(lines)

    def status_text(self) -> str:
        config = self.load_config()
        if not config:
            return "No connectors configured. Run: connectors catalog"
        lines = []
        for name, cfg in sorted(config.items()):
            if not isinstance(cfg, dict):
                lines.append(f"{name}: invalid configuration (expected an object)")
                continue
            info = self.servers.get(name, {"status": "not connected", "tools": []})
            extra = f" ({len(info['tools'])} tools)" if info.get("tools") else ""
            lines.append(f"{name} [{cfg.get('type', 'stdio')}]: {info['status']}{extra}")
        return "\n".join(lines)


def _catalog_text() -> str:
    lines = ["Connector catalog:"]
    for name, preset in CONNECTOR_CATALOG.items():
        requirements = ", ".join(preset.get("requires", []))
        trust = f"; {preset['trust']}" if preset.get("trust") else ""
        lines.append(f"  {name}: {preset['description']} — needs {requirements}{trust}")
    lines.append("Add one with: connectors add <github|gmail|canva>")
    return "\n".join(lines)


def register(engine):
    try:
        import mcp  # noqa: F401
    except ImportError:
        def _cmd_missing(ctx):
            return "❌ the mcp package is not installed — pip install mcp"
        engine.registry.register("connectors", _cmd_missing, "MCP connectors (needs: pip install mcp)")
        return

    existing_manager = getattr(engine, "connector_manager", None)
    if existing_manager is not None:
        existing_manager.shutdown()
    manager = ConnectorManager(engine)
    engine.connector_manager = manager

    def _cmd_connectors(ctx):
        args = ctx.args
        try:
            if not args or args[0] in {"list", "status"}:
                return manager.status_text()
            action = args[0].lower()
            if action == "catalog":
                return _catalog_text()
            if action == "doctor":
                return manager.doctor_text()
            if action == "add" and len(args) >= 2:
                name = manager.add_preset(args[1].lower(), args[2] if len(args) > 2 else None)
                return f"✅ connector '{name}' added; run: connectors connect {name}"
            if action == "add-http" and len(args) == 3:
                manager.add_http(args[1], args[2])
                return f"✅ HTTP connector '{args[1]}' added"
            if action == "add-stdio" and len(args) >= 3:
                manager.add_stdio(args[1], args[2], args[3:])
                return f"✅ stdio connector '{args[1]}' added"
            if action == "remove" and len(args) == 2:
                manager.remove(args[1])
                return f"✅ connector '{args[1]}' removed"
            if action == "connect" and len(args) == 2:
                started = manager.connect(args[1])
                return f"⏳ connecting to {args[1]}..." if started else manager.status_text()
            if action == "disconnect" and len(args) == 2:
                manager.disconnect(args[1])
                return f"🔌 disconnected from {args[1]}"
            if action == "reconnect" and len(args) == 2:
                manager.reconnect(args[1])
                return f"⏳ reconnecting to {args[1]}..."
            if action == "tools" and len(args) == 2:
                return manager.tools_text(args[1])
        except (OSError, ValueError) as exc:
            return f"❌ {exc}"
        return (
            "usage: connectors [list|catalog|doctor|add <preset> [name]|"
            "add-http <name> <https-url>|add-stdio <name> <command> [args...]|"
            "connect|disconnect|reconnect|remove|tools <name>]"
        )

    engine.registry.register("connectors", _cmd_connectors, "Manage stdio/HTTP MCP connectors and presets")
    for name, cfg in manager.load_config().items():
        if isinstance(cfg, dict) and cfg.get("autoConnect") is True:
            manager.connect(name)
