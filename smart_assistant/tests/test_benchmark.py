"""اختبارات القياس — القياس نفسه لازم يكون صح قبل ما نصدّق أرقامه."""
import benchmark
import pytest


def test_intent_accuracy_is_measured(bare_engine):
    for name, _ in benchmark.INTENT_CASES:
        assert isinstance(name, str)
    r = benchmark.measure_intent_accuracy(bare_engine)
    assert 0 <= r.value <= 100


def test_labelled_set_covers_both_languages():
    """نيزوكو بتدّعي إنها بتفهم اللغتين — الادعاء لازم يتقاس فيهم."""
    arabic = [p for p, _ in benchmark.INTENT_CASES if any("؀" <= c <= "ۿ" for c in p)]
    english = [p for p, _ in benchmark.INTENT_CASES if p.isascii()]
    assert len(arabic) >= 5
    assert len(english) >= 5


def test_false_match_rate_is_zero_on_free_text(bare_engine):
    """مطابقة غلط أسوأ من عدم المطابقة — دي بتنفذ حاجة مقصدتهاش."""
    r = benchmark.measure_false_match_rate(bare_engine)
    assert r.value == 0.0, r.failures


def test_typo_correction_is_measured_separately(bare_engine):
    """التصحيح الإملائي طبقة تانية غير القاموس — خلطهم بيدي رقم غلط."""
    r = benchmark.measure_typo_correction(bare_engine)
    assert "Typo" in r.name


def test_local_resolution_is_a_percentage(bare_engine):
    r = benchmark.measure_local_resolution(bare_engine)
    assert 0 <= r.value <= 100


def test_repo_map_measure_runs_or_skips_cleanly(bare_engine):
    r = benchmark.measure_repo_map(bare_engine)
    assert r.skipped or r.value == 100.0, r.failures


def test_latency_is_reported_in_ms(bare_engine):
    r = benchmark.measure_local_latency(bare_engine)
    assert "ms" in r.unit
    assert r.value < 50      # المسار المحلي لازم يفضل فوري


def test_model_measure_skips_without_a_brain(bare_engine, monkeypatch):
    """من غير مخ بنقول 'اتخطى' — منعدّهوش صفر، ده هيبوّظ الرقم."""
    import brain
    monkeypatch.setattr(brain.Brain, "ready", lambda self: False)
    r = benchmark.measure_brain_latency(bare_engine)
    assert r.skipped is True


def test_run_without_model_makes_no_network_call(bare_engine, monkeypatch):
    import brain
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda *a, **k: pytest.fail("benchmark called the model when it should not"),
    )
    benchmark.run(bare_engine, include_model=False)


def test_a_broken_measure_does_not_stop_the_rest(bare_engine, monkeypatch):
    def boom(engine):
        raise RuntimeError("measure exploded")
    monkeypatch.setattr(benchmark, "MEASURES", (boom, benchmark.measure_local_latency))
    results = benchmark.run(bare_engine, include_model=False)
    assert len(results) == 2
    assert results[0].skipped is True


def test_report_renders_every_result(bare_engine):
    out = benchmark.report(benchmark.run(bare_engine, include_model=False))
    assert "Intent accuracy" in out
    assert "measured, not estimated" in out


def test_report_lists_what_missed():
    results = [benchmark.Result("X", 50.0, "%", "half", failures=["a → b"])]
    assert "a → b" in benchmark.report(results)


def test_skipped_results_are_marked_not_counted_as_zero():
    results = [benchmark.Result("X", 0.0, "%", "no brain", skipped=True)]
    out = benchmark.report(results)
    assert "skipped" in out
    assert "0.00" not in out


# ── القياسات الواسعة ─────────────────────────────────────────────────

def test_edit_correctness_is_perfect(bare_engine):
    r = benchmark.measure_edit_correctness(bare_engine)
    assert r.skipped or r.value == 100.0, r.failures


def test_edit_cases_include_both_applying_and_refusing():
    """رفض التعديل الغامض **نجاح** — لو المجموعة فيها حالات ناجحة بس،
    الرقم مش بيقيس الأمان خالص."""
    expects = {c[4] for c in benchmark.EDIT_CASES}
    assert expects == {"ok", "refused"}


def test_edit_safety_properties_hold(bare_engine):
    r = benchmark.measure_edit_safety(bare_engine)
    assert r.skipped or r.value == 100.0, r.failures


def test_tool_call_parsing_is_perfect(bare_engine):
    r = benchmark.measure_tool_call_parsing(bare_engine)
    assert r.value == 100.0, r.failures


def test_reasoning_cases_have_checkable_answers():
    """كل سؤال إجابته قابلة للتحقق آليًا — مش رأي. ده شرط عشان الرقم
    يبقى قياس مش انطباع."""
    for question, expected in benchmark.REASONING_CASES:
        assert expected
        assert len(expected) < 10, question


def test_reasoning_set_covers_both_languages():
    arabic = [q for q, _ in benchmark.REASONING_CASES
              if any("؀" <= c <= "ۿ" for c in q)]
    assert len(arabic) >= 2


def test_answer_matching_is_lenient_about_shape():
    assert benchmark._answer_matches("72", "72")
    assert benchmark._answer_matches("**72** pens in total", "72")
    assert benchmark._answer_matches("The answer is Yes.", "yes")


def test_answer_matching_is_strict_about_value():
    """72 مش 720 ولا 172 — المطابقة المتساهلة أوي بتخلي الرقم بلا معنى."""
    assert not benchmark._answer_matches("720", "72")
    assert not benchmark._answer_matches("172", "72")
    assert not benchmark._answer_matches("7.2", "72")
    assert not benchmark._answer_matches("no", "yes")


def test_reasoning_skips_when_no_model_is_actually_reachable(bare_engine, monkeypatch):
    """ready() بترجع True لـ Ollama حتى لو مش مشغّل. لو صدّقناها،
    الرقم بيطلع 0% ويقرا 'الموديل غبي' والحقيقة 'مفيش موديل'."""
    import brain
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: brain.BrainReply(text="", error="connection refused"),
    )
    r = benchmark.measure_reasoning(bare_engine)
    assert r.skipped is True
    assert "actually reachable" in r.detail


def test_reasoning_scores_when_the_model_answers(bare_engine, monkeypatch):
    import brain
    answers = {q: a for q, a in benchmark.REASONING_CASES}
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: brain.BrainReply(
            text=answers.get(messages[-1]["content"], "ok"), provider="f", label="F"),
    )
    r = benchmark.measure_reasoning(bare_engine)
    assert r.skipped is False
    assert r.value == 100.0


def test_reasoning_reports_the_call_cost(bare_engine, monkeypatch):
    """4 نداءات لكل سؤال مش تفصيلة — لازم تبان قبل ما حد يشغّلها."""
    import brain
    monkeypatch.setattr(brain.Brain, "ready", lambda self: True)
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda self, messages, **kw: brain.BrainReply(text="72", provider="f", label="F"),
    )
    r = benchmark.measure_reasoning_verified(bare_engine)
    assert "calls" in r.detail


def test_fast_run_skips_every_model_measure(bare_engine, monkeypatch):
    import brain
    monkeypatch.setattr(
        brain.Brain, "chat",
        lambda *a, **k: pytest.fail("a fast benchmark run called the model"),
    )
    benchmark.run(bare_engine, include_model=False)
