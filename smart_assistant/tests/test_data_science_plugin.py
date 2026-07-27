import data_science_plugin as dsp
import pytest

requires_pandas = pytest.mark.skipif(not dsp.PANDAS_AVAILABLE, reason="pandas not installed")
requires_matplotlib = pytest.mark.skipif(not dsp.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")


@pytest.fixture
def sample_csv(tmp_path):
    path = tmp_path / "sample.csv"
    lines = ["name,age,salary"]
    for i in range(20):
        age = 20 + i
        salary = age * 1000  # perfectly correlated with age by construction
        lines.append(f"person{i},{age},{salary}")
    lines.append("missing_person,,")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@requires_pandas
def test_csv_describe_reports_shape_and_stats(make_ctx, sample_csv):
    result = dsp._cmd_csv_describe(make_ctx("csv_describe", [str(sample_csv)]))
    assert "21 rows" in result
    assert "3 columns" in result
    assert "name" in result and "age" in result and "salary" in result


@requires_pandas
def test_csv_describe_flags_missing_values(make_ctx, sample_csv):
    result = dsp._cmd_csv_describe(make_ctx("csv_describe", [str(sample_csv)]))
    assert "missing" in result.lower() or "فاضية" in result
    assert "age: 1" in result


@requires_pandas
def test_csv_describe_missing_file(make_ctx, tmp_path):
    result = dsp._cmd_csv_describe(make_ctx("csv_describe", [str(tmp_path / "nope.csv")]))
    assert result.startswith("❌")


@requires_pandas
def test_csv_describe_empty_file(make_ctx, tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("a,b,c\n", encoding="utf-8")
    result = dsp._cmd_csv_describe(make_ctx("csv_describe", [str(f)]))
    assert "empty" in result


@requires_pandas
@requires_matplotlib
def test_csv_plot_creates_image_file(make_ctx, sample_csv, tmp_path):
    out = tmp_path / "plot.png"
    result = dsp._cmd_csv_plot(make_ctx("csv_plot", [str(sample_csv), "age", str(out)]))
    assert result.startswith("✅")
    assert out.is_file()
    assert out.stat().st_size > 0


@requires_pandas
@requires_matplotlib
def test_csv_plot_all_chart_kinds(make_ctx, sample_csv, tmp_path):
    for kind in ("hist", "line", "bar", "box"):
        out = tmp_path / f"plot_{kind}.png"
        result = dsp._cmd_csv_plot(make_ctx("csv_plot", [str(sample_csv), "age", str(out), kind]))
        assert result.startswith("✅"), f"{kind} failed: {result}"
        assert out.is_file()


@requires_pandas
def test_csv_plot_unknown_column(make_ctx, sample_csv, tmp_path):
    result = dsp._cmd_csv_plot(make_ctx("csv_plot", [str(sample_csv), "bogus_col", str(tmp_path / "x.png")]))
    assert result.startswith("❌")


@requires_pandas
def test_csv_plot_unknown_kind(make_ctx, sample_csv, tmp_path):
    result = dsp._cmd_csv_plot(make_ctx("csv_plot", [str(sample_csv), "age", str(tmp_path / "x.png"), "bogus"]))
    assert result.startswith("❌")


@requires_pandas
def test_csv_correlate_detects_perfect_correlation(make_ctx, sample_csv):
    result = dsp._cmd_csv_correlate(make_ctx("csv_correlate", [str(sample_csv)]))
    # salary = age * 1000 by construction -> correlation should be ~1.0
    assert "1.0" in result


@requires_pandas
def test_csv_correlate_needs_two_numeric_columns(make_ctx, tmp_path):
    f = tmp_path / "onecol.csv"
    f.write_text("name\na\nb\nc\n", encoding="utf-8")
    result = dsp._cmd_csv_correlate(make_ctx("csv_correlate", [str(f)]))
    assert result.startswith("❌")


@requires_pandas
@requires_matplotlib
def test_csv_correlate_with_output_saves_heatmap(make_ctx, sample_csv, tmp_path):
    out = tmp_path / "heatmap.png"
    result = dsp._cmd_csv_correlate(make_ctx("csv_correlate", [str(sample_csv), str(out)]))
    assert result.startswith("✅")
    assert out.is_file()
