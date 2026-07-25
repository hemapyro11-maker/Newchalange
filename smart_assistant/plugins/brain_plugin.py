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
        "🧠 تظبيط مخ نيزوكو — كل الخيارات دي مجانية ومن غير كارت ائتمان.",
        "",
        "الأسرع (دقيقتين): Gemini — أقوى واحد في العربي وأسخى في الحد اليومي",
        "  1. افتح: https://aistudio.google.com/apikey",
        "  2. سجّل دخول بحساب جوجل واعمل API key",
        "  3. ارجع هنا واكتب:  brain_key gemini <المفتاح>",
        "",
        "بدايل مجانية كمان (تقدر تضيف أكتر من واحد — بيتبدلوا تلقائي):",
    ]
    for r in rows:
        if not r["signup"] or r["local"]:
            continue
        mark = "✅" if r["has_key"] else "⬜"
        lines.append(f"  {mark} {r['label']:<16} {r['rpd']} طلب/يوم — {r['signup']}")
    lines += [
        "",
        "أوفلاين بالكامل (بياناتك متخرجش من الجهاز):",
        "  ⬜ Ollama — نزّله من https://ollama.com وبعدين: ollama pull llama3.2",
        "",
        f"الحالة دلوقتي: {len(ready)} مخ جاهز." if ready
        else "الحالة دلوقتي: ⚠️ مفيش أي مخ متظبط لسه.",
        "",
        "ليه تضيف أكتر من واحد؟ الحدود بتتجمع، والانتقال بين المزوّدين",
        "بيوزّع الطلبات فمتوصلش لحد الدقيقة بتاع أي واحد فيهم.",
    ]
    return "\n".join(lines)


def _cmd_brain_status(ctx) -> str:
    b = brain.get_brain()
    rows = b.status()
    lines = ["🧠 حالة المخ:\n"]
    total_left = 0
    for r in rows:
        if not r["enabled"]:
            icon, note = "⏸️", "متوقف"
        elif not r["has_key"]:
            icon, note = "⬜", "مفيش مفتاح"
        elif r["cold_for"]:
            icon, note = "❄️", f"مقفول مؤقتًا {r['cold_for']}ث"
        else:
            icon, note = "✅", "جاهز"
            total_left += max(0, r["rpd"] - r["used_today"])
        privacy = " 🔓" if r["trains_on_input"] else ""
        lines.append(
            f"  {icon} {r['label']:<16} {r['used_today']}/{r['rpd']} النهارده — {note}{privacy}"
        )
        lines.append(f"       نموذج: {r['model']}  |  سياق: {r['context']:,} توكن")

    cfg = brain.load_config()
    lines += [
        "",
        f"📊 متبقي النهارده: ~{total_left:,} طلب",
        f"🎚️ الوضع: {'عميق (MoA — أبطأ وأدق)' if cfg.get('deep_mode') else 'عادي (سريع)'}",
        f"🔒 محلي بس: {'شغال' if cfg.get('local_only') else 'مقفول'}",
    ]
    if any(r["trains_on_input"] and r["has_key"] and r["enabled"] for r in rows):
        lines.append(
            "\n🔓 = الخطة المجانية للمزوّد ده بتقول إن كلامك ممكن يستخدموه\n"
            "     لتحسين نماذجهم. لو مش عايز كده: brain_local on"
        )
    return "\n".join(lines)


def _cmd_brain_key(ctx) -> str:
    if len(ctx.args) < 2:
        return (
            "usage: brain_key <provider> <api_key>\n"
            f"المزوّدين: {', '.join(p for p in brain.PROVIDERS if brain.PROVIDERS[p].needs_key)}"
        )
    provider, key = ctx.args[0].lower(), ctx.args[1]
    if provider not in brain.PROVIDERS:
        return f"❌ مزوّد مش معروف: {provider}"
    how = brain.set_key(provider, key)
    label = brain.PROVIDERS[provider].label
    if how == "keyring":
        return f"✅ اتحفظ مفتاح {label} في مخزن أسرار النظام (مش نص عادي)"
    return (
        f"⚠️ اتحفظ مفتاح {label} كنص عادي في brain_config.json — "
        "keyring مش متاح على الجهاز ده.\nالملف مستثنى من git، بس خليك واخد بالك."
    )


def _cmd_brain_forget_key(ctx) -> str:
    if not ctx.args:
        return "usage: brain_forget_key <provider>"
    provider = ctx.args[0].lower()
    if provider not in brain.PROVIDERS:
        return f"❌ مزوّد مش معروف: {provider}"
    brain.clear_key(provider)
    return f"🗑️ اتمسح مفتاح {brain.PROVIDERS[provider].label}"


def _cmd_brain_model(ctx) -> str:
    if len(ctx.args) < 2:
        cfg = brain.load_config()
        lines = ["النماذج الحالية:"]
        for name, prov in brain.PROVIDERS.items():
            lines.append(f"  {name:<12} {cfg.get('models', {}).get(name, prov.model)}")
        lines.append("\nusage: brain_model <provider> <model_name>")
        return "\n".join(lines)
    provider, model = ctx.args[0].lower(), ctx.args[1]
    if provider not in brain.PROVIDERS:
        return f"❌ مزوّد مش معروف: {provider}"
    cfg = brain.load_config()
    cfg.setdefault("models", {})[provider] = model
    brain.save_config(cfg)
    return f"✅ {brain.PROVIDERS[provider].label} هيستخدم: {model}"


def _cmd_brain_mode(ctx) -> str:
    cfg = brain.load_config()
    if not ctx.args:
        cur = "عميق" if cfg.get("deep_mode") else "عادي"
        return f"الوضع الحالي: {cur}\nusage: brain_mode normal|deep"
    mode = ctx.args[0].lower()
    if mode in ("deep", "عميق"):
        cfg["deep_mode"] = True
        brain.save_config(cfg)
        return (
            "🧠 الوضع العميق اتشغّل — كذا نموذج هيجاوبوا وأقواهم هيدمج ردودهم.\n"
            "⚠️ بيستهلك ~4 أضعاف الحصة وأبطأ. للأسئلة المهمة بس."
        )
    cfg["deep_mode"] = False
    brain.save_config(cfg)
    return "⚡ الوضع العادي — نموذج واحد، أسرع وأوفر في الحصة."


def _cmd_brain_local(ctx) -> str:
    cfg = brain.load_config()
    if not ctx.args:
        return f"محلي بس: {'شغال' if cfg.get('local_only') else 'مقفول'}\nusage: brain_local on|off"
    on = ctx.args[0].lower() in ("on", "شغال", "1", "true")
    cfg["local_only"] = on
    brain.save_config(cfg)
    if on:
        return (
            "🔒 محلي بس — مفيش أي كلام هيخرج من جهازك خالص.\n"
            "محتاج Ollama شغال، وإلا الكلام الحر مش هيتفهم."
        )
    return "☁️ المزوّدين السحابيين المجانيين رجعوا يشتغلوا."


def _cmd_brain_dict(ctx) -> str:
    known = {c.name for c in ctx.engine.registry.list_commands()}
    rep = intents.coverage_report(known)
    cache = intents.load_cache()
    lines = [
        "📖 القاموس المحلي (اللي بيوفّر عليك الحصة):\n",
        f"  إجمالي الأوامر المسجّلة: {rep['total']}",
        f"  متغطّية بالقاموس الجاهز:  {rep['dictionary']}",
        f"  اتعلمتها من استخدامك:     {rep['learned']}",
        f"  صيغ كلام محفوظة:          {len(cache)}",
        "",
        "كل صيغة محفوظة = نداء واحد بس دفعته مرة واحدة في حياتك،",
        "وبعدها بتتحل محليًا ببلاش للأبد.",
    ]
    if cache:
        lines.append("\nآخر صيغ اتعلمتها:")
        for phrase, cmd in list(cache.items())[-8:]:
            lines.append(f"  • \"{phrase}\" → {cmd}")
    return "\n".join(lines)


def _cmd_brain_forget_dict(ctx) -> str:
    n = intents.forget_all()
    return f"🗑️ اتمسحت {n} صيغة من القاموس المتعلّم (القاموس الجاهز فاضل زي ما هو)"


def register(engine):
    r = engine.registry.register
    r("brain_setup", _cmd_brain_setup, "brain_setup — خطوات تظبيط مخ مجاني بالترتيب")
    r("brain_status", _cmd_brain_status, "brain_status — حالة كل مخ والحصة المتبقية")
    r("brain_key", _cmd_brain_key, "brain_key <provider> <key> — تسجيل مفتاح مزوّد مجاني")
    r("brain_forget_key", _cmd_brain_forget_key, "brain_forget_key <provider> — مسح مفتاح")
    r("brain_model", _cmd_brain_model, "brain_model <provider> <model> — تغيير النموذج المستخدم")
    r("brain_mode", _cmd_brain_mode, "brain_mode normal|deep — عادي (سريع) أو عميق (أدق، أغلى)")
    r("brain_local", _cmd_brain_local, "brain_local on|off — قفل كل المزوّدين السحابيين")
    r("brain_dict", _cmd_brain_dict, "brain_dict — تغطية القاموس المحلي والصيغ المتعلّمة")
    r("brain_forget_dict", _cmd_brain_forget_dict, "brain_forget_dict — مسح الصيغ المتعلّمة")
