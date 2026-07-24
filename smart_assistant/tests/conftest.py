"""
conftest.py — يظبط sys.path عشان الاختبارات تقدر تعمل import مباشر
لـ core_engine و أي plugin (بما إنهم مش package بايثون عادي، بل بيتحملوا
ديناميكياً وقت التشغيل الحقيقي عبر core_engine.load_plugins).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins"))

import pytest

import core_engine
from core_engine import AssistantEngine, CommandContext


@pytest.fixture(autouse=True)
def isolate_state_dir(tmp_path, monkeypatch):
    """كل اختبار بيشتغل بمجلد حالة (skills.json) خاص بيه، عشان محدش
    يكتب فوق smart_assistant/skills.json الحقيقي بتاع المستخدم."""
    monkeypatch.setattr(core_engine, "default_state_dir", lambda: tmp_path)


@pytest.fixture
def bare_engine(tmp_path):
    """Engine من غير أي plugins (plugins_dirs فاضي) — لاختبار core_engine لوحده."""
    return AssistantEngine(plugins_dirs=[tmp_path / "no_plugins_here"])


@pytest.fixture
def make_ctx(bare_engine):
    def _make(raw: str, args: list[str], engine=None):
        return CommandContext(raw=raw, args=args, engine=engine or bare_engine)
    return _make
