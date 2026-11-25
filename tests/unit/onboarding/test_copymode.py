"""Copy mode: draft, gate, copy, paste by hand. Every refusal, the clipboard, both languages."""
from __future__ import annotations

import argparse
import json

import pytest
from onboard_helpers import gate_fail, gate_pass, make_draft

from profile_wrap import cli, config, copymode, i18n, policy


def refused(ws, slug, gate=gate_pass):
    with pytest.raises(copymode.CopyRefused) as err:
        copymode.prepare(ws, slug, gate_fn=gate)
    return err.value


@pytest.mark.parametrize("slug", [None, "", "../x", "UPPER", "a b", 12])
def test_a_bad_draft_name_is_refused(first_run_ws, slug):
    assert refused(first_run_ws, slug).code == "copy.refused.slug"


def test_a_missing_draft_is_refused(first_run_ws):
    assert refused(first_run_ws, "nothing-here").code == "copy.refused.nodraft"


def test_a_posted_draft_is_not_offered_again(first_run_ws):
    make_draft(first_run_ws, "done", status="posted")
    assert refused(first_run_ws, "done").code == "copy.refused.status"


def test_an_empty_caption_is_refused(first_run_ws):
    make_draft(first_run_ws, "blank", caption="")
    assert refused(first_run_ws, "blank").code == "copy.refused.empty"


def test_a_caption_over_the_limit_is_refused(first_run_ws):
    make_draft(first_run_ws, "long", caption="x" * 5000)
    assert refused(first_run_ws, "long").code == "copy.refused.problem"


def test_a_draft_that_fails_the_gate_is_never_offered_for_pasting(first_run_ws):
    make_draft(first_run_ws, "bad")
    err = refused(first_run_ws, "bad", gate=gate_fail)
    assert err.code == "copy.refused.gate" and err.params["count"] == 1 and "40 tickets" in err.params["first"]


def test_a_passing_draft_returns_the_pieces_to_paste(first_run_ws):
    make_draft(first_run_ws, "good", caption="Line one.\n\nLine two.", first_comment="Link in the comments.", alt="Alt.")
    piece = copymode.prepare(first_run_ws, "good", gate_fn=gate_pass)
    assert piece["caption"] == "Line one.\n\nLine two." and piece["first_comment"] == "Link in the comments."
    assert piece["alt"] == "Alt." and piece["open_url"] == "https://www.linkedin.com/feed/"


def test_the_gate_is_run_without_writing_gates_json(first_run_ws):
    make_draft(first_run_ws, "good")
    seen = []
    copymode.prepare(first_run_ws, "good", gate_fn=lambda slug, ws, write: seen.append(write) or gate_pass(slug, ws))
    assert seen == [False]


# ------------------------------------------------------------------ clipboard

def test_each_platform_gets_its_own_clipboard_tool():
    have = lambda *names: (lambda n: "/bin/" + n if n in names else None)
    assert copymode.clipboard_command("darwin", have("pbcopy")) == ["pbcopy"]
    assert copymode.clipboard_command("linux", have("xclip"))[0] == "xclip"
    assert copymode.clipboard_command("linux", have("wl-copy")) == ["wl-copy"]
    assert copymode.clipboard_command("win32", have("powershell"))[-1].endswith("Set-Clipboard -Value ([Console]::In.ReadToEnd())")
    assert copymode.clipboard_command("linux", have()) is None
    assert copymode.clipboard_command("darwin", have()) is None


def test_arabic_text_goes_to_the_clipboard_as_utf8():
    sent = {}

    def run(cmd, input=None, **kw):
        sent["cmd"], sent["input"] = cmd, input
        return argparse.Namespace(returncode=0)

    assert copymode.to_clipboard("مرحبا", platform="linux", which=lambda n: "/bin/xsel" if n == "xsel" else None, run=run)
    assert sent["input"].decode("utf-8") == "مرحبا" and sent["cmd"][0] == "xsel"


def test_no_clipboard_tool_or_a_failing_one_returns_false():
    assert copymode.to_clipboard("x", platform="linux", which=lambda n: None) is False
    assert copymode.to_clipboard("x", platform="linux", which=lambda n: "/bin/x",
                                 run=lambda *a, **k: argparse.Namespace(returncode=1)) is False

    def boom(*a, **k):
        raise OSError("gone")

    assert copymode.to_clipboard("x", platform="linux", which=lambda n: "/bin/x", run=boom) is False


# ------------------------------------------------------------------ the command

def args(ws, slug, **kw):
    ns = argparse.Namespace(slug=slug, workspace=str(ws), profile=None, part="caption", print_only=False, lang=None)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_the_copy_command_copies_the_caption_and_says_what_to_do_next(first_run_ws, capsys):
    make_draft(first_run_ws, "good", caption="Hello there.")
    copied = []
    code = copymode.cmd_copy(args(first_run_ws, "good"), copier=lambda t: copied.append(t) or True, gate_fn=gate_pass)
    out = capsys.readouterr().out
    assert code == policy.EXIT_OK and copied == ["Hello there."]
    assert i18n.t("copy.cli.copied", "en") in out and "https://www.linkedin.com/feed/" in out


def test_the_copy_command_refuses_a_failing_draft_and_copies_nothing(first_run_ws, capsys):
    make_draft(first_run_ws, "bad")
    copied = []
    code = copymode.cmd_copy(args(first_run_ws, "bad"), copier=lambda t: copied.append(t) or True, gate_fn=gate_fail)
    assert code == policy.EXIT_FAIL and copied == []
    assert "did not pass" in capsys.readouterr().err


def test_the_refusal_comes_in_arabic_on_request(first_run_ws, capsys):
    code = copymode.cmd_copy(args(first_run_ws, "missing", lang="ar"), copier=lambda t: True, gate_fn=gate_pass)
    assert code == policy.EXIT_FAIL
    assert i18n.t("copy.refused.nodraft", "ar", slug="missing") in capsys.readouterr().err


def test_the_language_follows_the_ui_language_setting(first_run_ws, capsys):
    config.set_value(first_run_ws, "board.ui_language", '"ar"')
    copymode.cmd_copy(args(first_run_ws, "missing"), copier=lambda t: True, gate_fn=gate_pass)
    assert i18n.t("copy.refused.nodraft", "ar", slug="missing") in capsys.readouterr().err


def test_without_a_clipboard_the_text_is_printed_to_copy_by_hand(first_run_ws, capsys):
    make_draft(first_run_ws, "good", caption="Hello there.")
    code = copymode.cmd_copy(args(first_run_ws, "good"), copier=lambda t: False, gate_fn=gate_pass)
    out = capsys.readouterr().out
    assert code == policy.EXIT_OK and "Hello there." in out and i18n.t("copy.cli.noclip", "en") in out


def test_a_part_with_nothing_in_it_is_refused(first_run_ws, capsys):
    make_draft(first_run_ws, "good")
    code = copymode.cmd_copy(args(first_run_ws, "good", part="first-comment"), copier=lambda t: True, gate_fn=gate_pass)
    assert code == policy.EXIT_FAIL and "nothing for that part" in capsys.readouterr().err


def test_the_command_is_registered_and_never_opens_the_api(first_run_ws, capsys):
    make_draft(first_run_ws, "good")
    code = cli.main(["copy", "good", "--print", "--workspace", str(first_run_ws), "--lang", "en"])
    # the real gate may fail on a bare draft; either way no token or network is involved
    assert code in (policy.EXIT_OK, policy.EXIT_FAIL)
    assert not (first_run_ws / "work" / "posting.lock").exists()
    assert json.loads(config.config_path(first_run_ws).read_text(encoding="utf-8"))["posting"]["mode"] == "copy"
