"""Explicit bilingual reply preference on top of automatic language matching."""
from __future__ import annotations

import brain


def _cmd_reply_language(ctx):
    cfg = brain.load_config()
    if not ctx.args:
        return f"Reply language: {cfg.get('reply_language', 'auto')} (auto, ar, or en)"
    value = ctx.args[0].lower()
    if value not in {"auto", "ar", "en"}:
        return "usage: reply_language auto|ar|en"
    cfg["reply_language"] = value
    brain.save_config(cfg)
    labels = {"auto": "match each message", "ar": "Arabic", "en": "English"}
    return f"Reply language: {labels[value]}"


def register(engine):
    engine.registry.register("reply_language", _cmd_reply_language,
                             "reply_language auto|ar|en — match each message or lock Arabic/English")
