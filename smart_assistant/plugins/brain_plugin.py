"""
brain_plugin.py — أوامر إدارة "مخ" نيزوكو: تظبيط المزوّدين المجانيين،
متابعة الحصة المتبقية، تبديل الأوضاع، وإدارة القاموس المتعلّم.

كل المزوّدين المدعومين ليهم خطة مجانية دايمة من غير كارت ائتمان.
`brain_setup` بيوريك الخطوات بالترتيب وروابط التسجيل المباشرة.

الأوامر: brain_setup, brain_status, brain_key, brain_forget_key,
brain_model, brain_mode, brain_local, brain_dict, brain_forget_dict
"""
from __future__ import annotations

import brain
import intents


def _cmd_brain_setup(ctx) -> str:
    rows = ctx.engine.brain.status() if hasattr(ctx.engine, "brain") else brain.get_brain().status()
    ready = [r for r in rows if r["has_key"] and r["enabled"]]
    lines = [
        "🧠 Set up Nezuko's brain — every option here is free, no card needed.",
        "",
        "Fastest (2 min): Gemini — best Arabic of the free tiers, most generous daily cap",
        "  1. Open https://aistudio.google.com/apikey",
        "  2. Sign in with Google and create an API key",
        "  3. Come back and run:  brain_key gemini <key>",
        "",
        "Other free providers (add several — they fail over automatically):",
    ]
    for r in rows:
        if not r["signup"] or r["local"]:
            continue
        mark = "✅" if r["has_key"] else "⬜"
        lines.append(f"  {mark} {r['label']:<16} {r['rpd']}/day — {r['signup']}")
    lines += [
        "",
        "Fully offline (nothing leaves your machine):",
        "  ⬜ Ollama — get it from https://ollama.com then: ollama pull llama3.2",
        "",
        f"Status: {len(ready)} brain ready." if ready
        else "Status: ⚠️ no brain configured yet.",
        "",
        "Why add more than one? The daily caps add up, and spreading calls",
        "across providers keeps you under each one's per-minute limit.",
    ]
    return "\n".join(lines)


def _cmd_brain_status(ctx) -> str:
    b = brain.get_brain()
    rows = b.status()
    lines = ["🧠 Brain status:\n"]
    total_left = 0
    for r in rows:
        if not r["enabled"]:
            icon, note = "⏸️", "disabled"
        elif not r["has_key"]:
            icon, note = "⬜", "no key"
        elif r["cold_for"]:
            icon, note = "❄️", f"cooling down {r['cold_for']}s"
        else:
            icon, note = "✅", "ready"
            total_left += max(0, r["rpd"] - r["used_today"])
        privacy = " 🔓" if r["trains_on_input"] else ""
        lines.append(
            f"  {icon} {r['label']:<16} {r['used_today']}/{r['rpd']} today — {note}{privacy}"
        )
        lines.append(f"       model: {r['model']}  |  context: {r['context']:,} tokens")

    cfg = brain.load_config()
    lines += [
        "",
        f"📊 Left today: ~{total_left:,} requests",
        f"🎚️ Mode: {'deep (MoA — slower, sharper)' if cfg.get('deep_mode') else 'normal (fast)'}",
        f"🔒 Local only: {'on' if cfg.get('local_only') else 'off'}",
    ]
    if any(r["trains_on_input"] and r["has_key"] and r["enabled"] for r in rows):
        lines.append(
            "\n🔓 = this provider's free tier says your input may be used to\n"
            "     improve their models. To stop that: brain_local on"
        )
    return "\n".join(lines)


def _cmd_brain_key(ctx) -> str:
    if len(ctx.args) < 2:
        return (
            "usage: brain_key <provider> <api_key>\n"
            f"providers: {', '.join(p for p in brain.PROVIDERS if brain.PROVIDERS[p].needs_key)}"
        )
    provider, key = ctx.args[0].lower(), ctx.args[1]
    if provider not in brain.PROVIDERS:
        return f"❌ unknown provider: {provider}"
    how = brain.set_key(provider, key)
    label = brain.PROVIDERS[provider].label
    if how == "keyring":
        return f"✅ {label} key saved to the system secret store (not plain text)"
    return (
        f"⚠️ {label} key saved as plain text in brain_config.json — "
        "no keyring backend on this machine.\nThe file is git-ignored, but be aware."
    )


def _cmd_brain_forget_key(ctx) -> str:
    if not ctx.args:
        return "usage: brain_forget_key <provider>"
    provider = ctx.args[0].lower()
    if provider not in brain.PROVIDERS:
        return f"❌ unknown provider: {provider}"
    brain.clear_key(provider)
    return f"🗑️ removed the {brain.PROVIDERS[provider].label} key"


def _cmd_brain_model(ctx) -> str:
    if len(ctx.args) < 2:
        cfg = brain.load_config()
        lines = ["Current models:"]
        for name, prov in brain.PROVIDERS.items():
            lines.append(f"  {name:<12} {cfg.get('models', {}).get(name, prov.model)}")
        lines.append("\nusage: brain_model <provider> <model_name>")
        return "\n".join(lines)
    provider, model = ctx.args[0].lower(), ctx.args[1]
    if provider not in brain.PROVIDERS:
        return f"❌ unknown provider: {provider}"
    cfg = brain.load_config()
    cfg.setdefault("models", {})[provider] = model
    brain.save_config(cfg)
    return f"✅ {brain.PROVIDERS[provider].label} will use: {model}"


def _cmd_brain_mode(ctx) -> str:
    cfg = brain.load_config()
    if not ctx.args:
        if cfg.get("deep_mode"):
            cur = "deep (always)"
        elif cfg.get("auto_deep"):
            cur = "auto (deep only when the question needs working out)"
        elif cfg.get("verify_mode"):
            cur = "verify (checks its own answer on hard questions)"
        else:
            cur = "normal"
        return (
            f"Current mode: {cur}\n"
            "usage: brain_mode normal|verify|auto|deep\n"
            "  normal — 1 call, fastest\n"
            "  verify — 4 calls on hard questions, answers then checks itself\n"
            "  auto   — 4 calls on hard questions, several models merged\n"
            "  deep   — 4 calls on every question"
        )
    mode = ctx.args[0].lower()
    if mode in ("deep", "عميق"):
        cfg["deep_mode"] = True
        brain.save_config(cfg)
        return (
            "🧠 Deep mode on — several models answer and the strongest merges them.\n"
            "⚠️ Uses ~4× the quota and is slower. Save it for questions that matter."
        )
    if mode in ("auto", "تلقائي", "تلقاءي"):
        cfg["deep_mode"] = False
        cfg["auto_deep"] = True
        cfg["verify_mode"] = False
        brain.save_config(cfg)
        return (
            "🎯 Auto mode — normal speed for ordinary messages, deep mode only for\n"
            "questions that need working out (why/compare/calculate/debug).\n"
            "Costs the extra quota on those questions only, not on every message."
        )
    if mode in ("verify", "verified", "تحقق", "مراجعه", "مراجعة"):
        cfg["deep_mode"] = False
        cfg["auto_deep"] = False
        cfg["verify_mode"] = True
        brain.save_config(cfg)
        return (
            "🔍 Verify mode — on hard questions Nezuko answers, then writes\n"
            "verification questions against its own answer, answers those\n"
            "independently, and rewrites what the checks contradict.\n"
            "Published research puts this at 50-70% fewer hallucinations.\n"
            "Costs 4 calls instead of 1 — but the quota is free, so the real\n"
            "price is time, not money."
        )
    cfg["deep_mode"] = False
    cfg["auto_deep"] = False
    cfg["verify_mode"] = False
    brain.save_config(cfg)
    return "⚡ Normal mode — one model, faster and cheaper."


def _cmd_brain_local(ctx) -> str:
    cfg = brain.load_config()
    if not ctx.args:
        return f"Local only: {'on' if cfg.get('local_only') else 'off'}\nusage: brain_local on|off"
    on = ctx.args[0].lower() in ("on", "شغال", "1", "true")
    cfg["local_only"] = on
    brain.save_config(cfg)
    if on:
        return (
            "🔒 Local only — nothing leaves your machine.\n"
            "Needs Ollama running, otherwise free-form text will not be understood."
        )
    return "☁️ Free cloud providers are back on."


def _cmd_brain_dict(ctx) -> str:
    known = {c.name for c in ctx.engine.registry.list_commands()}
    rep = intents.coverage_report(known)
    cache = intents.load_cache()
    lines = [
        "📖 Local dictionary (this is what saves your quota):\n",
        f"  Registered commands:   {rep['total']}",
        f"  Covered by dictionary: {rep['dictionary']}",
        f"  Learned from your use: {rep['learned']}",
        f"  Saved phrasings:       {len(cache)}",
        "",
        "Each saved phrasing = one call you paid once, ever —",
        "free locally from then on.",
    ]
    if cache:
        lines.append("\nRecently learned:")
        for phrase, cmd in list(cache.items())[-8:]:
            lines.append(f"  • \"{phrase}\" → {cmd}")
    return "\n".join(lines)


def _cmd_brain_forget_dict(ctx) -> str:
    n = intents.forget_all()
    return f"🗑️ cleared {n} learned phrasings (the built-in dictionary is untouched)"


def register(engine):
    r = engine.registry.register
    r("brain_setup", _cmd_brain_setup, "brain_setup — step-by-step guide to a free brain")
    r("brain_status", _cmd_brain_status, "brain_status — every provider and how much quota is left")
    r("brain_key", _cmd_brain_key, "brain_key <provider> <key> — save a free provider key")
    r("brain_forget_key", _cmd_brain_forget_key, "brain_forget_key <provider> — remove a key")
    r("brain_model", _cmd_brain_model, "brain_model <provider> <model> — change which model is used")
    r("brain_mode", _cmd_brain_mode, "brain_mode normal|deep — fast, or slower and sharper")
    r("brain_local", _cmd_brain_local, "brain_local on|off — disable every cloud provider")
    r("brain_dict", _cmd_brain_dict, "brain_dict — local dictionary coverage and learned phrasings")
    r("brain_forget_dict", _cmd_brain_forget_dict, "brain_forget_dict — clear learned phrasings")
