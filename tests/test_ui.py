"""Presentational components in golit.ui."""

from __future__ import annotations

import golit.ui as ui
import polars as pl


def test_card_includes_title_subtitle_footer_and_body():
    out = ui.card("the body", title="Overview", subtitle="sub", footer="foot")
    assert "Overview" in out and "sub" in out and "foot" in out and "the body" in out


def test_columns_equal_vs_custom_widths():
    assert "md:grid-cols-3" in ui.columns([1, 2, 3])
    custom = ui.columns(["a", "b"], widths=[5, 7])
    assert "md:col-span-5" in custom and "md:col-span-7" in custom


def test_columns_renders_dataframe_child_as_table():
    df = pl.DataFrame({"a": [1, 2]})
    out = ui.columns([df, "plain html"])
    assert "golit-table" in out  # the df child went through render_value
    assert "plain html" in out


def test_tabs_sets_default_index_and_panels():
    out = ui.tabs({"Chart": "<svg/>", "Data": "<table/>"}, default="Data")
    assert "x-data=\"{ tab: 1 }\"" in out
    assert out.count("x-show=") == 2


def test_expander_open_flag():
    assert "<details" in ui.expander("More", "body", open=True)
    assert " open>" in ui.expander("More", "body", open=True)
    assert " open>" not in ui.expander("More", "body")


def test_metric_delta_direction_and_colors():
    assert "▲" in ui.metric("R", "1", delta="+8%")
    assert "text-green-600" in ui.metric("R", "1", delta="+8%")
    assert "▼" in ui.metric("R", "1", delta="-8%")
    assert "text-red-600" in ui.metric("R", "1", delta="-8%")
    # inverse flips meaning; off is neutral
    assert "text-green-600" in ui.metric("R", "1", delta="-8%", delta_color="inverse")
    assert "text-on-surface-variant" in ui.metric("R", "1", delta="-8%", delta_color="off")


def test_scorecard_value_label_delta_icon_caption():
    out = ui.scorecard(
        "Revenue", "$84.2k", delta="+8%", icon="payments", caption="vs last month",
        kind="primary",
    )
    assert "golit-scorecard" in out
    assert "Revenue" in out and "$84.2k" in out
    assert "▲" in out and "text-green-600" in out  # shares the metric delta pill
    assert "material-symbols-outlined" in out and "payments" in out  # icon
    assert "text-primary" in out  # kind accent on the icon
    assert "vs last month" in out  # caption footer


def test_scorecard_minimal_has_no_icon_or_caption():
    out = ui.scorecard("Rows", "1,204")
    assert "Rows" in out and "1,204" in out
    assert "material-symbols-outlined" not in out  # no icon requested
    assert "▲" not in out and "▼" not in out  # no delta requested


def test_scorecard_inverse_delta_color():
    # down is good under inverse (e.g. churn dropping)
    assert "text-green-600" in ui.scorecard("Churn", "2%", delta="-0.4%", delta_color="inverse")


def test_scorecard_escapes_user_values():
    out = ui.scorecard("<x>", "<b>v</b>", caption="<i>c</i>")
    assert "<x>" not in out and "&lt;x&gt;" in out
    assert "<b>v</b>" not in out and "&lt;b&gt;v&lt;/b&gt;" in out


def test_alert_kind_classes_and_icon():
    out = ui.alert("watch out", kind="warning", title="Heads up")
    assert "bg-amber-50" in out and "warning" in out and "Heads up" in out


def test_badge_kind():
    assert "bg-green-100" in ui.badge("ok", kind="success")
    assert "bg-surface-container-high" in ui.badge("x")


def test_progress_clamps_to_0_100():
    assert "width: 100%" in ui.progress(5, total=1)  # over 100% clamps
    assert "width: 0%" in ui.progress(-1, total=1)  # below 0 clamps
    assert "width: 50%" in ui.progress(0.5)


def test_skeleton_line_count():
    assert ui.skeleton(lines=4).count("animate-pulse") == 4


def test_table_highlight_and_truncation():
    df = pl.DataFrame({"region": ["N", "S"], "revenue": [1, 2]})
    out = ui.table(df, highlight="revenue")
    assert "text-primary" in out  # highlighted column styled
    big = pl.DataFrame({"x": list(range(100))})
    assert "showing 10 of 100 rows" in ui.table(big, max_rows=10)


def test_code_escapes_and_tags_language():
    out = ui.code("<b>&", lang="html")
    assert "&lt;b&gt;&amp;" in out  # escaped
    assert ">html<" in out  # language tag


def test_json_view_pretty_prints():
    out = ui.json_view({"a": 1, "b": [1, 2]})
    assert "&quot;a&quot;" in out and "json" in out


def test_components_escape_untrusted_text():
    assert "<script>" not in ui.badge("<script>alert(1)</script>")
    assert "<script>" not in ui.heading("<script>")
    assert "<script>" not in ui.caption("<script>")


def test_markdown_subset():
    md = ui.markdown(
        "# H1\n\nA **bold** word, *em*, and `code`.\n\n"
        "- a\n- b\n\n1. one\n2. two\n\n> quote\n\n---\n\n"
        "[link](https://x.dev)\n\n```python\nx = 1\n```\n"
    )
    assert "<h1" in md
    assert "<strong>bold</strong>" in md
    assert "<em>em</em>" in md
    assert "<code" in md
    assert md.count("<li>") == 4  # 2 ul + 2 ol
    assert "list-disc" in md and "list-decimal" in md
    assert "<blockquote" in md
    assert 'href="https://x.dev"' in md
    assert "golit-code" in md  # fenced block


def test_markdown_escapes_html():
    assert "<script>" not in ui.markdown("<script>alert(1)</script>")
