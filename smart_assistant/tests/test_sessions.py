import json
import time

import pytest
import sessions


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "_base_dir", lambda: tmp_path)


def _msgs(*texts):
    out = []
    for t in texts:
        out.append({"role": "user", "content": t})
        out.append({"role": "assistant", "content": "رد"})
    return out


# ── الحفظ والاسترجاع ─────────────────────────────────────────────────

def test_save_and_load_roundtrip():
    sessions.save("s1", _msgs("إزيك"))
    assert sessions.load("s1") == _msgs("إزيك")


def test_load_missing_session_returns_none():
    assert sessions.load("nope") is None


def test_empty_messages_are_not_saved():
    """من غير الشرط ده، كل فتح وقفل للبرنامج كان هيسيب جلسة فاضية."""
    sessions.save("empty", [])
    assert sessions.load("empty") is None


def test_saving_twice_keeps_the_original_creation_time():
    sessions.save("s1", _msgs("أول"))
    created = sessions.meta("s1")["created"]
    time.sleep(1.05)
    sessions.save("s1", _msgs("أول", "تاني"))
    assert sessions.meta("s1")["created"] == created
    assert sessions.meta("s1")["updated"] != created


def test_new_ids_are_unique():
    assert len({sessions.new_id() for _ in range(50)}) == 50


# ── العناوين ─────────────────────────────────────────────────────────

def test_title_comes_from_the_first_user_message():
    assert sessions.make_title(_msgs("افحص الملف ده")) == "افحص الملف ده"


def test_long_title_is_truncated():
    title = sessions.make_title(_msgs("ط" * 200))
    assert len(title) <= sessions.TITLE_MAX + 1
    assert title.endswith("…")


def test_title_collapses_whitespace():
    assert sessions.make_title(_msgs("كلام    كتير\n\nومسافات")) == "كلام كتير ومسافات"


def test_title_falls_back_when_no_user_message():
    assert sessions.make_title([{"role": "assistant", "content": "x"}]) == "محادثة من غير عنوان"


def test_explicit_title_overrides_the_generated_one():
    sessions.save("s1", _msgs("حاجة"), title="عنوان مخصص")
    assert sessions.meta("s1")["title"] == "عنوان مخصص"


# ── القايمة ──────────────────────────────────────────────────────────

def test_list_is_newest_first():
    sessions.save("old", _msgs("قديم"))
    time.sleep(1.05)
    sessions.save("new", _msgs("جديد"))
    assert [s["id"] for s in sessions.list_all()][0] == "new"


def test_list_counts_user_turns():
    sessions.save("s1", _msgs("واحد", "اتنين", "تلاتة"))
    assert sessions.list_all()[0]["turns"] == 3


def test_list_skips_corrupted_files_instead_of_crashing():
    sessions.save("good", _msgs("سليم"))
    (sessions.sessions_dir() / "broken.json").write_text("{not json", encoding="utf-8")
    ids = [s["id"] for s in sessions.list_all()]
    assert ids == ["good"]


def test_list_skips_files_without_an_id():
    sessions.save("good", _msgs("سليم"))
    (sessions.sessions_dir() / "weird.json").write_text(
        json.dumps({"title": "مفيش id"}), encoding="utf-8"
    )
    assert [s["id"] for s in sessions.list_all()] == ["good"]


def test_list_is_empty_when_nothing_saved():
    assert sessions.list_all() == []


# ── الحذف ────────────────────────────────────────────────────────────

def test_delete_removes_one_session():
    sessions.save("s1", _msgs("حاجة"))
    assert sessions.delete("s1") is True
    assert sessions.load("s1") is None


def test_delete_missing_session_is_false():
    assert sessions.delete("nope") is False


def test_delete_all_clears_everything():
    for i in range(3):
        sessions.save(f"s{i}", _msgs(f"م {i}"))
    assert sessions.delete_all() == 3
    assert sessions.list_all() == []


def test_old_sessions_are_pruned_past_the_cap(monkeypatch):
    monkeypatch.setattr(sessions, "MAX_SESSIONS", 5)
    for i in range(9):
        sessions.save(f"s{i:02d}", _msgs(f"م {i}"))
        time.sleep(0.01)
    assert len(sessions.list_all()) <= 5


# ── أمان اسم الملف ───────────────────────────────────────────────────

def test_session_id_cannot_escape_the_sessions_directory():
    """معرّف الجلسة بيتولّد داخليًا، بس ممكن ييجي من ملف على القرص
    عدّله حد — فلازم يتنضف قبل ما يبقى اسم ملف."""
    sessions.save("../../evil", _msgs("حاجة"))
    written = list(sessions.sessions_dir().glob("*.json"))
    assert len(written) == 1
    # المهم إن الملف قعد جوه مجلد الجلسات، مش إن الاسم فيه نقط
    assert written[0].resolve().parent == sessions.sessions_dir().resolve()


def test_weird_characters_in_id_are_sanitised():
    sessions.save('a/b\\c:d*e', _msgs("حاجة"))
    name = list(sessions.sessions_dir().glob("*.json"))[0].name
    assert all(ch not in name for ch in '/\\:*')


# ── الوقت النسبي ─────────────────────────────────────────────────────

def test_relative_time_says_now_for_fresh():
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    assert sessions.relative_time(now) == "دلوقتي"


def test_relative_time_reports_hours():
    import datetime
    then = (datetime.datetime.now() - datetime.timedelta(hours=3)).isoformat(timespec="seconds")
    assert "3 ساعة" in sessions.relative_time(then)


def test_relative_time_reports_days():
    import datetime
    then = (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat(timespec="seconds")
    assert "2 يوم" in sessions.relative_time(then)


def test_relative_time_handles_garbage_input():
    assert sessions.relative_time("not-a-date") == "not-a-date"


def test_relative_time_handles_empty():
    assert sessions.relative_time("") == "—"


# ── الكتابة الذرية ───────────────────────────────────────────────────

def test_no_temp_file_is_left_behind():
    sessions.save("s1", _msgs("حاجة"))
    assert list(sessions.sessions_dir().glob("*.tmp")) == []
