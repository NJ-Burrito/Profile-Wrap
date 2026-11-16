"""first_comment_promise: a caption that promises a link in the first comment needs a first comment with a URL."""
from __future__ import annotations

import pytest
from gate_helpers import make_draft, write_config

from profile_wrap.gate import run_gate
from profile_wrap.gate.promise import promise_phrases


def _promise(res):
    return [f for f in res["findings"] if f["check"] == "first_comment_promise"]


def test_promise_without_a_first_comment_fails(ws):
    make_draft(ws, "d1", "A plain claim about reviews.\nLink in the first comment.\n")
    res = run_gate("d1", ws)
    f = _promise(res)
    assert res["summary"] == "FAIL" and len(f) == 1 and f[0]["severity"] == "fail"
    assert "first_comment.txt is missing" in f[0]["message"]
    assert not res["checks"]["first_comment_promise"]["ok"]


def test_promise_with_a_first_comment_without_url_fails(ws):
    make_draft(ws, "d1", "A plain claim.\nDetails in the first comment.\n", first_comment="Thanks for reading.\n")
    f = _promise(run_gate("d1", ws))
    assert len(f) == 1 and "has no link" in f[0]["message"]


def test_empty_first_comment_fails(ws):
    make_draft(ws, "d1", "A plain claim.\nThe link is in the comments.\n", first_comment="   \n")
    assert "empty" in _promise(run_gate("d1", ws))[0]["message"]


def test_promise_with_a_url_passes(ws):
    make_draft(ws, "d1", "A plain claim.\nLink in the first comment.\n",
               first_comment="Read more: https://example.com/guide\n")
    res = run_gate("d1", ws)
    assert _promise(res) == [] and res["summary"] == "PASS"


def test_no_promise_needs_no_first_comment(ws):
    make_draft(ws, "d1", "I read the comments and changed one thing.\n")
    assert _promise(run_gate("d1", ws)) == []


@pytest.mark.parametrize("caption", [
    "جملة بسيطة عن المراجعة.\nالرابط في التعليق الأول.\n",
    "جملة بسيطة.\nالتفاصيل في أول تعليق 👇\n",
    "جملة بسيطة.\nرابط المصدر في التعليقات.\n",
])
def test_arabic_promise_fails_without_first_comment_and_passes_with_url(ws, caption):
    make_draft(ws, "d1", caption, lang="ar")
    assert _promise(run_gate("d1", ws)), caption
    make_draft(ws, "d1", caption, lang="ar", first_comment="https://example.com/guide\n")
    assert _promise(run_gate("d1", ws)) == []


def test_mode_off_and_warn(ws):
    make_draft(ws, "d1", "A plain claim.\nLink in the first comment.\n")
    write_config(ws, gate={"first_comment_promise": "warn"})
    res = run_gate("d1", ws)
    assert res["summary"] == "PASS" and _promise(res)[0]["severity"] == "warn"
    write_config(ws, gate={"first_comment_promise": "off"})
    assert _promise(run_gate("d1", ws)) == []


def test_phrase_list_english_and_arabic():
    assert promise_phrases("Full guide: link in the first comment.")
    assert promise_phrases("Source in the 1st comment")
    assert promise_phrases("التفاصيل في التعليق الاول")
    assert not promise_phrases("A comment on the code review.")
