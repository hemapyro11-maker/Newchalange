import brain
import hooks
import permissions
import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "_base_dir", lambda: tmp_path)
    monkeypatch.setattr(brain, "_HAS_KEYRING", False)
    monkeypatch.setattr(hooks, "_base_dir", lambda: tmp_path)
    brain.reset_brain()
    yield
    brain.reset_brain()


# ── الصلاحيات ────────────────────────────────────────────────────────

def test_nothing_is_allowed_by_default():
    """المبدأ الأساسي: القايمة بتبدأ فاضية، مفيش أي حاجة بتعدي لوحدها."""
    assert permissions.allowed() == set()
    assert permissions.is_allowed("probe") is False


def test_allow_then_is_allowed():
    ok, _ = permissions.allow("probe")
    assert ok is True
    assert permissions.is_allowed("probe") is True


def test_allow_is_case_insensitive():
    permissions.allow("PROBE")
    assert permissions.is_allowed("probe") is True


def test_allow_persists_to_config():
    permissions.allow("probe")
    assert "probe" in brain.load_config()["allowed_commands"]


def test_allow_twice_is_harmless():
    permissions.allow("probe")
    ok, msg = permissions.allow("probe")
    assert ok is True
    assert "بالفعل" in msg


def test_empty_command_is_rejected():
    ok, _ = permissions.allow("   ")
    assert ok is False


def test_revoke_removes_permission():
    permissions.allow("probe")
    assert permissions.revoke("probe") is True
    assert permissions.is_allowed("probe") is False


def test_revoke_unknown_is_false():
    assert permissions.revoke("nope") is False


def test_revoke_all_clears_the_list():
    permissions.allow("probe")
    permissions.allow("hexdump")
    assert permissions.revoke_all() == 2
    assert permissions.allowed() == set()


# ── الأوامر الممنوعة نهائيًا ─────────────────────────────────────────

@pytest.mark.parametrize("cmd", sorted(permissions.never_allowed()))
def test_dangerous_commands_can_never_be_allowed(cmd):
    """دي محتاجة عين بشرية في كل مرة — والمنع في الكود نفسه مش مجرد
    تحذير في الواجهة."""
    ok, msg = permissions.allow(cmd)
    assert ok is False
    assert "مينفعش" in msg
    assert permissions.is_allowed(cmd) is False


def test_run_is_on_the_never_list():
    assert "run" in permissions.never_allowed()


def test_never_list_wins_even_if_config_was_edited_by_hand():
    """حد عدّل brain_config.json بإيده وحط run في القايمة — لازم
    يتجاهل برضه."""
    cfg = brain.load_config()
    cfg["allowed_commands"] = ["run", "probe"]
    brain.save_config(cfg)
    assert permissions.is_allowed("run") is False
    assert permissions.is_allowed("probe") is True


def test_non_string_entries_in_config_are_ignored():
    cfg = brain.load_config()
    cfg["allowed_commands"] = ["probe", 42, None]
    brain.save_config(cfg)
    assert permissions.allowed() == {"probe"}


# ── الـ hooks ────────────────────────────────────────────────────────

def test_hooks_start_empty():
    data = hooks.load()
    assert all(data[e] == [] for e in hooks.EVENTS)


def test_add_and_read_back():
    ok, _ = hooks.add("after_command", "echo خلص")
    assert ok is True
    assert hooks.commands_for("after_command") == ["echo خلص"]


def test_add_rejects_unknown_event():
    ok, msg = hooks.add("whenever", "echo x")
    assert ok is False
    assert "مش معروف" in msg


def test_add_rejects_empty_command():
    ok, _ = hooks.add("startup", "   ")
    assert ok is False


def test_duplicate_hook_is_not_added_twice():
    hooks.add("startup", "echo x")
    hooks.add("startup", "echo x")
    assert hooks.commands_for("startup") == ["echo x"]


def test_remove_deletes_a_hook():
    hooks.add("startup", "echo x")
    assert hooks.remove("startup", "echo x") is True
    assert hooks.commands_for("startup") == []


def test_remove_unknown_is_false():
    assert hooks.remove("startup", "nope") is False


def test_clear_removes_everything():
    hooks.add("startup", "echo a")
    hooks.add("on_error", "echo b")
    assert hooks.clear() == 2
    assert hooks.commands_for("startup") == []


def test_corrupted_hooks_file_falls_back_to_empty():
    hooks._path().write_text("{not json", encoding="utf-8")
    data = hooks.load()
    assert all(data[e] == [] for e in hooks.EVENTS)


def test_non_list_values_in_file_are_ignored():
    import json
    hooks._path().write_text(json.dumps({"startup": "not a list"}), encoding="utf-8")
    assert hooks.commands_for("startup") == []


# ── إطلاق الأحداث ────────────────────────────────────────────────────

class _FakeEngine:
    def __init__(self):
        self.sent = []

    def submit_hook(self, text):
        self.sent.append(text)


def test_fire_submits_each_hook_command():
    hooks.add("startup", "echo a")
    hooks.add("startup", "echo b")
    eng = _FakeEngine()
    hooks.fire(eng, "startup")
    assert eng.sent == ["echo a", "echo b"]


def test_fire_substitutes_the_command_placeholder():
    hooks.add("after_command", "echo خلص {command}")
    eng = _FakeEngine()
    hooks.fire(eng, "after_command", command="probe")
    assert eng.sent == ["echo خلص probe"]


def test_fire_on_an_event_with_no_hooks_does_nothing():
    eng = _FakeEngine()
    hooks.fire(eng, "startup")
    assert eng.sent == []


def test_a_broken_hook_does_not_stop_the_others():
    hooks.add("startup", "first")
    hooks.add("startup", "second")

    class Flaky(_FakeEngine):
        def submit_hook(self, text):
            if text == "first":
                raise RuntimeError("مكسور")
            self.sent.append(text)

    eng = Flaky()
    hooks.fire(eng, "startup")
    assert eng.sent == ["second"]


def test_hooks_use_the_dedicated_submit_path():
    """راجع: لو الـ hooks استخدمت submit العادية، أمر مربوط بـ
    after_command كان هيطلّع after_command تاني بلا نهاية."""
    hooks.add("after_command", "echo x")
    eng = _FakeEngine()
    hooks.fire(eng, "after_command", command="probe")
    assert eng.sent == ["echo x"]
    assert not hasattr(eng, "submit")  # مش بتستخدم submit العادية
