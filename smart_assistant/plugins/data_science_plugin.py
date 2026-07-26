"""
data_science_plugin.py — تحليل بيانات حقيقي عبر pandas/matplotlib
(مكتبات مفتوحة المصدر ومجانية بالكامل، نفس الأدوات القياسية في مجال
علم البيانات — بدون أي API مدفوع أو خدمة سحابية).

الأوامر: csv_describe, csv_plot, csv_correlate
"""
from __future__ import annotations

import pathlib

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use("Agg")  # بدون شاشة — التطبيق بيولّد صور مش يعرضها في نافذة
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def _load_csv(path: pathlib.Path):
    try:
        return pd.read_csv(path), None
    except Exception as e:
        return None, f"❌ تعذرت قراءة CSV: {e}"


def _cmd_csv_describe(ctx) -> str:
    if not PANDAS_AVAILABLE:
        return "❌ باكدج pandas مش متثبت — ثبّته بـ: pip install pandas"
    if not ctx.args:
        return "usage: csv_describe <file.csv>"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    df, err = _load_csv(path)
    if err:
        return err
    if df.empty:
        return "⚠  الملف فاضي (مفيش صفوف)"

    lines = [f"📊 {df.shape[0]} صف × {df.shape[1]} عمود"]
    lines.append(f"الأعمدة: {', '.join(df.columns)}")
    numeric = df.select_dtypes(include="number")
    if not numeric.empty:
        lines.append("")
        lines.append(numeric.describe().round(3).to_string())
    missing = df.isna().sum()
    missing = missing[missing > 0]
    if not missing.empty:
        lines.append("")
        lines.append("⚠  قيم فاضية (missing):")
        for col, count in missing.items():
            lines.append(f"  {col}: {count}")
    return "\n".join(lines)


def _cmd_csv_plot(ctx) -> str:
    if not PANDAS_AVAILABLE:
        return "❌ باكدج pandas مش متثبت — ثبّته بـ: pip install pandas"
    if not MATPLOTLIB_AVAILABLE:
        return "❌ باكدج matplotlib مش متثبت — ثبّته بـ: pip install matplotlib"
    if len(ctx.args) < 3:
        return "usage: csv_plot <file.csv> <column> <output.png> [kind=hist]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    column, output = ctx.args[1], ctx.args[2]
    kind = ctx.args[3] if len(ctx.args) > 3 else "hist"
    if kind not in ("hist", "line", "bar", "box"):
        return f"❌ kind غير معروف: {kind} (المتاح: hist, line, bar, box)"

    df, err = _load_csv(path)
    if err:
        return err
    if column not in df.columns:
        return f"❌ العمود {column} مش موجود (المتاح: {', '.join(df.columns)})"

    try:
        fig, ax = plt.subplots(figsize=(8, 5))
        if kind == "hist":
            df[column].dropna().plot.hist(ax=ax, bins=30)
        elif kind == "line":
            df[column].dropna().plot.line(ax=ax)
        elif kind == "bar":
            df[column].value_counts().head(20).plot.bar(ax=ax)
        elif kind == "box":
            df[[column]].dropna().plot.box(ax=ax)
        ax.set_title(column)
        out_path = pathlib.Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=100, bbox_inches="tight")
        plt.close(fig)
    except Exception as e:
        return f"❌ فشل الرسم: {e}"
    return f"✅ اتعمل الرسم ({kind}) في {out_path}"


def _cmd_csv_correlate(ctx) -> str:
    if not PANDAS_AVAILABLE:
        return "❌ باكدج pandas مش متثبت — ثبّته بـ: pip install pandas"
    if not ctx.args:
        return "usage: csv_correlate <file.csv> [output.png]"
    path = pathlib.Path(ctx.args[0])
    if not path.is_file():
        return f"❌ الملف مش موجود: {path}"
    df, err = _load_csv(path)
    if err:
        return err
    numeric = df.select_dtypes(include="number")
    if numeric.shape[1] < 2:
        return "❌ محتاج عمودين رقميين على الأقل عشان نحسب correlation"
    corr = numeric.corr().round(3)

    if len(ctx.args) > 1:
        if not MATPLOTLIB_AVAILABLE:
            return "❌ باكدج matplotlib مش متثبت — ثبّته بـ: pip install matplotlib"
        try:
            fig, ax = plt.subplots(figsize=(7, 6))
            im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
            ax.set_xticks(range(len(corr.columns)))
            ax.set_yticks(range(len(corr.columns)))
            ax.set_xticklabels(corr.columns, rotation=45, ha="right")
            ax.set_yticklabels(corr.columns)
            fig.colorbar(im)
            out_path = pathlib.Path(ctx.args[1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(out_path, dpi=100, bbox_inches="tight")
            plt.close(fig)
        except OSError as e:
            return f"❌ فشل الحفظ: {e}"
        return f"✅ correlation heatmap في {out_path}\n\n{corr.to_string()}"
    return corr.to_string()


def register(engine):
    engine.registry.register("csv_describe", _cmd_csv_describe, "csv_describe <file.csv> — real descriptive statistics (pandas)")
    engine.registry.register("csv_plot", _cmd_csv_plot, "csv_plot <file.csv> <column> <out.png> [kind] — plot a column (hist/line/bar/box)")
    engine.registry.register("csv_correlate", _cmd_csv_correlate, "csv_correlate <file.csv> [out.png] — correlation matrix across columns")
