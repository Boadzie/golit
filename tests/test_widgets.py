"""The added reactive input widgets: coercion and rendering."""

from __future__ import annotations

import datetime

import pytest
from golit import button, date, multiselect, radio, switch, textarea


def _bound(widget, name="w"):
    widget.bind(name)
    return widget


def test_radio_coerces_to_option_and_rejects_unknown():
    w = _bound(radio(["A", "B", "C"], default="B"))
    assert w.default == "B"
    assert w.coerce("C") == "C"
    html = w.render("B")
    assert html.count('type="radio"') == 3
    assert 'value="B" checked' in html
    with pytest.raises(ValueError):
        w.coerce("Z")


def test_multiselect_coerces_comma_list_and_renders_checked():
    w = _bound(multiselect(["N", "S", "E"], default=["N", "E"]))
    assert w.coerce("N,E") == ["N", "E"]
    assert w.coerce("") == []
    assert w.coerce("S") == ["S"]
    html = w.render(["N", "E"])
    # 2 boxes pre-checked (the third "checked" is the :checked selector in hx-vals).
    assert 'data-val="N" checked' in html
    assert 'data-val="E" checked' in html
    assert 'data-val="S" checked' not in html


def test_switch_coerces_boolean_strings():
    w = _bound(switch("Live", default=True))
    assert w.default is True
    assert w.coerce("true") is True
    assert w.coerce("false") is False
    assert w.coerce("on") is True
    assert "peer" in w.render(True)


def test_date_coerces_iso_else_none():
    w = _bound(date())
    assert w.coerce("2026-06-02") == datetime.date(2026, 6, 2)
    assert w.coerce("") is None
    assert 'value="2026-06-02"' in w.render(datetime.date(2026, 6, 2))


def test_textarea_passthrough_and_rows():
    w = _bound(textarea(rows=6, placeholder="notes"))
    assert w.coerce("hello") == "hello"
    html = w.render("body")
    assert 'rows="6"' in html
    assert ">body</textarea>" in html


def test_button_coerces_nonce_and_posts_timestamp():
    w = _bound(button("Run"))
    assert w.default == 0
    assert w.coerce("1717300000000") == 1717300000000
    assert w.coerce("nope") == 0
    html = w.render(0)
    assert "Date.now()" in html
    assert "Run" in html
    assert 'hx-trigger="click"' in html


def test_bind_defaults_label_from_name():
    w = radio(["A", "B"])
    w.bind("my_choice")
    assert w.label == "My Choice"
