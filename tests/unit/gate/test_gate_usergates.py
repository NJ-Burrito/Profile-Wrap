"""User-owned gates (hooks/gate_*.py) run inside the gate and cannot crash it."""
from __future__ import annotations

from gate_helpers import make_draft

from njli.gate import run_gate
from njli.gate.usergates import list_user_gates


def hook(ws, name, body):
    (ws / "hooks").mkdir(exist_ok=True)
    (ws / "hooks" / f"gate_{name}.py").write_text(body, encoding="utf-8")


def test_user_gate_findings_fail_warn_and_are_listed(ws):
    hook(ws, "tone", "def check(draft, meta, surfaces, cfg):\n"
                     "    out = []\n"
                     "    if 'shout' in surfaces['caption']: out.append('no shouting')\n"
                     "    out.append({'severity': 'warn', 'message': 'consider a question', 'token': 'q'})\n"
                     "    return out\n")
    make_draft(ws, "d1", "Please shout.\n")
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL" and res["user_gates"] == ["gate_tone"]
    assert any("custom:gate_tone" in f and "no shouting" in f for f in res["fails"])
    assert any("consider a question" in w for w in res["warnings"])
    make_draft(ws, "d2", "Quiet words.\n")
    assert run_gate("d2", ws)["summary"] == "PASS"


def test_broken_user_gates_become_fail_lines(ws):
    hook(ws, "crash", "def check(*a):\n    raise RuntimeError('boom')\n")
    hook(ws, "nocheck", "x = 1\n")
    hook(ws, "badtype", "def check(*a):\n    return 'nope'\n")
    hook(ws, "baditem", "def check(*a):\n    return [42]\n")
    hook(ws, "syntax", "def check(:\n")
    hook(ws, "none", "def check(*a):\n    return None\n")
    make_draft(ws, "d1", "Plain.\n")
    res = run_gate("d1", ws)
    text = "\n".join(res["fails"])
    for needle in ("RuntimeError: boom", "defines no check", "must return a list", "unreadable finding", "SyntaxError"):
        assert needle in text, (needle, text)
    assert len(list_user_gates(ws)) == 6


def test_no_hooks_folder_is_fine(ws):
    make_draft(ws, "d1", "Plain.\n")
    assert run_gate("d1", ws)["user_gates"] == []
