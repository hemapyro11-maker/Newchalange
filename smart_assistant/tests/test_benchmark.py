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
