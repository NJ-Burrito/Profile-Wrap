"""Golden files for every backend, rendered on every OS (the renderers are pure).

Real machine paths never appear in a golden file: the test builds paths at run time and replaces them with
tokens (@HOME@, @WS@, @PY@, @PYZ@ ...) before comparing. Regenerate with NJLI_UPDATE_GOLDEN=1 and read the diff.
"""
from __future__ import annotations

import os
import plistlib
import xml.etree.ElementTree as ET
from pathlib import Path


from njli.schedule import backends as bk
from njli.schedule.jobs import Job, jobs_from_config, rule_for
from schedhelp import cfg_of

GOLDEN = Path(__file__).resolve().parent / "golden"
UPDATE = os.environ.get("NJLI_UPDATE_GOLDEN") == "1"


def posix_ctx(**kw) -> tuple[bk.Context, dict]:
    home = "/home/" + "demo-user"
    tok = {home: "@HOME@"}
    ws = f"{home}/nj-linkedin/demo"
    pyz = f"{home}/.local/share/nj-linkedin/runtime/current/njli.pyz"
    py = "/usr/bin/python3"
    tools = {"node": "/opt/homebrew/bin/node", "npx": "/opt/homebrew/bin/npx", "ffmpeg": "/opt/homebrew/bin/ffmpeg",
             "ffprobe": "/opt/homebrew/bin/ffprobe", "claude": f"{home}/.local/bin/claude"}
    ctx = bk.Context(profile="demo", workspace=ws, entry=[py, pyz], path_env="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                     tools=tools, home=home, uid=501)
    for k, v in kw.items():
        setattr(ctx, k, v)
    tok.update({ws: "@WS@", pyz: "@PYZ@"})
    return ctx, tok


def windows_ctx() -> tuple[bk.Context, dict]:
    drive = "D" + ":"
    home = drive + "\\Users\\demo-user"
    ws = drive + "\\njli demo\\nj-linkedin\\demo"          # a space in the path on purpose
    py = drive + "\\Python312\\python.exe"
    pyw = drive + "\\Python312\\pythonw.exe"
    pyz = home + "\\AppData\\Local\\nj-linkedin\\runtime\\current\\njli.pyz"
    ctx = bk.Context(profile="demo", workspace=ws, entry=[py, pyz], pythonw=pyw, home=home,
                     path_env="", tools={})
    return ctx, {ws: "@WS@", pyz: "@PYZ@", pyw: "@PYW@", py: "@PY@", home: "@HOME@"}


def golden_jobs() -> list[Job]:
    specs = {
        "build_week": {"when": "THU 10:00", "jitter_min": 20},
        "post_due": {"every_min": 15},
        "token_check": {"when": "DAILY 09:30"},
        "profile_review": {"every_days": 90},
        "connect_weekly": {"when": "SUN 10:00", "wake": True},
        "board": {"at_login": True},
    }
    import njli.schedule.jobs as J
    # post_due is only wanted for api_scheduled with an acknowledgement; the renderer does not care
    out = []
    for name, spec in specs.items():
        info = J.JOB_TABLE[name]
        rule = rule_for(name, spec)
        out.append(Job(name=name, argv=list(info["argv"]), rule=rule, timeout_s=int(info["timeout"]),
                       jitter_min=int(spec.get("jitter_min", 0)), wake=bool(spec.get("wake")),
                       pause_kind=info["pause"], long_lived=name in J.LONG_LIVED,
                       min_interval_days=rule.interval_days if rule.kind == "days" else 0))
    return out


def tokenise(text: str, tokens: dict) -> str:
    # longest first, so a workspace path is replaced before its home prefix
    for real in sorted(tokens, key=len, reverse=True):
        text = text.replace(real, tokens[real])
        text = text.replace(real.replace("\\", "\\\\"), tokens[real])
    return text.replace("\r\n", "\n")


def check(name: str, text: str) -> None:
    path = GOLDEN / name
    if UPDATE:
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.is_file(), f"golden file {name} is missing; run with NJLI_UPDATE_GOLDEN=1"
    assert text == path.read_text(encoding="utf-8").replace("\r\n", "\n"), f"{name} differs from its golden file"


def section(title: str, body: str) -> str:
    return f"=== {title} ===\n{body.rstrip(chr(10))}\n"


# ------------------------------------------------------------------ Windows

def test_windows_task_scheduler_xml_golden():
    ctx, tok = windows_ctx()
    parts, cmds = [], []
    for job in golden_jobs():
        art = bk.render_task_xml(ctx, job)
        parts.append(section(art.filename, tokenise(art.text, tok)))
        cmds += [" ".join(c) for c in bk.windows_commands(ctx, art, f"@WS@\\data\\schedule\\{art.filename}")]
    check("windows.txt", "".join(parts) + section("commands", tokenise("\n".join(cmds), tok)))


def test_windows_xml_is_well_formed_and_has_the_required_settings():
    ctx, _ = windows_ctx()
    ns = {"t": bk.XML_NS}
    for job in golden_jobs():
        root = ET.fromstring(bk.render_task_xml(ctx, job).text.split("?>", 1)[1])
        s = root.find("t:Settings", ns)
        assert s.find("t:StartWhenAvailable", ns).text == "true", "catch-up"
        assert s.find("t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
        assert s.find("t:WakeToRun", ns).text == ("true" if job.wake else "false"), "wake only when the job sets it"
        limit = s.find("t:ExecutionTimeLimit", ns).text
        assert (limit == "PT0S") == job.long_lived, "a per-job limit, none for the board"
        assert (s.find("t:RestartOnFailure", ns) is not None) == job.long_lived, "restart on failure for the board"
        assert (root.find("t:Triggers/t:LogonTrigger", ns) is not None) == (job.name == "board")
        cmd = root.find("t:Actions/t:Exec/t:Command", ns).text
        assert cmd.endswith("pythonw.exe"), "pythonw when present: no console window"
        args = root.find("t:Actions/t:Exec/t:Arguments", ns).text
        assert f"run {job.name} --workspace" in args and args.endswith('"'), "the workspace path has a space, so it is quoted"
        assert root.find("t:RegistrationInfo/t:URI", ns).text == f"\\njli-demo-{job.name}"


def test_windows_falls_back_to_python_exe_without_pythonw():
    ctx, _ = windows_ctx()
    ctx.pythonw = None
    cmd, _args = bk.windows_action(ctx, golden_jobs()[0])
    assert cmd.endswith("python.exe")


def test_windows_special_characters_are_escaped_in_xml():
    ctx, _ = windows_ctx()
    ctx.workspace = ctx.workspace + " & <co>"
    xml = bk.render_task_xml(ctx, golden_jobs()[0]).text
    ET.fromstring(xml.split("?>", 1)[1])
    assert "&amp;" in xml and "<co>" not in xml


# ------------------------------------------------------------------ systemd

def test_systemd_units_golden():
    ctx, tok = posix_ctx()
    parts, cmds = [], []
    for job in golden_jobs():
        arts = bk.render_systemd(ctx, job)
        for a in arts:
            parts.append(section(a.filename, tokenise(a.text, tok)))
        cmds += [" ".join(c) for c in bk.systemd_commands(arts)]
    check("systemd.txt", "".join(parts) + section("commands", tokenise("\n".join(cmds), tok)))


def test_systemd_timers_catch_up_and_jitter():
    ctx, _ = posix_ctx()
    by = {j.name: bk.render_systemd(ctx, j) for j in golden_jobs()}
    timer = next(a for a in by["build_week"] if a.kind == "unit-timer").text
    assert "Persistent=true" in timer and "RandomizedDelaySec=20min" in timer and "OnCalendar=Thu *-*-* 10:00:00" in timer
    service = next(a for a in by["build_week"] if a.kind == "unit-service").text
    assert "--no-jitter" in service, "systemd does the jitter, so the runner must not double it"
    assert "OnUnitActiveSec=15min" in next(a for a in by["post_due"] if a.kind == "unit-timer").text
    board = by["board"]
    assert len(board) == 1 and "Restart=on-failure" in board[0].text and "WantedBy=default.target" in board[0].text


# ------------------------------------------------------------------ cron

def test_crontab_block_golden():
    ctx, tok = posix_ctx()
    block = bk.render_cron_block(ctx, golden_jobs())
    check("cron.txt", tokenise(block, tok))


def test_cron_block_is_marked_wrapped_in_flock_and_replaced_not_duplicated():
    ctx, _ = posix_ctx()
    jobs = golden_jobs()
    block = bk.render_cron_block(ctx, jobs)
    assert block.startswith("# BEGIN njli:demo\n") and block.rstrip().endswith("# END njli:demo")
    lines = [ln for ln in block.splitlines() if ln and not ln.startswith("#")]
    assert len(lines) == len(jobs)
    assert all("flock -n" in ln for ln in lines)
    assert any(ln.startswith("@reboot ") for ln in lines), "the board starts at boot"
    mine = "MAILTO=me@example.invalid\n0 5 * * * backup.sh\n"
    once = bk.merge_cron_block(mine, ctx, jobs)
    twice = bk.merge_cron_block(once, ctx, jobs)
    assert once == twice, "installing twice does not duplicate the block"
    assert once.startswith(mine.rstrip("\n")), "the user's own lines are untouched"
    assert bk.strip_cron_block(once, "demo") == mine
    assert bk.strip_cron_block(bk.merge_cron_block("", ctx, jobs), "demo") == ""


def test_cron_times_map_correctly():
    ctx, _ = posix_ctx()
    by = {j.name: bk.render_cron_line(ctx, j).text for j in golden_jobs()}
    assert by["build_week"].startswith("0 10 * * 4 ")           # Thursday
    assert by["connect_weekly"].startswith("0 10 * * 0 ")       # Sunday is 0 in cron
    assert by["post_due"].startswith("*/15 * * * * ")
    assert by["token_check"].startswith("30 9 * * * ")
    assert by["profile_review"].startswith("0 9 * * * "), "every_days jobs fire daily; the runner skips the early ones"


# ------------------------------------------------------------------ launchd

def test_launchd_plists_golden_including_the_captured_path():
    ctx, tok = posix_ctx()
    parts, cmds = [], []
    for job in golden_jobs():
        art = bk.render_plist(ctx, job)
        parts.append(section(art.filename, tokenise(art.text, tok)))
        cmds += [" ".join(c) for c in bk.launchd_commands(ctx, art, f"@HOME@/Library/LaunchAgents/{art.filename}")]
        cmds += [" ".join(c) for c in bk.launchd_remove_commands(ctx, art.name)]
    check("launchd.txt", "".join(parts) + section("commands", tokenise("\n".join(cmds), tok)))


def test_launchd_plist_captures_resolved_tool_paths_and_path():
    ctx, _ = posix_ctx()
    for job in golden_jobs():
        d = plistlib.loads(bk.render_plist(ctx, job).text.encode("utf-8"))
        env = d["EnvironmentVariables"]
        assert env["PATH"] == ctx.path_env, "the user's PATH is captured, not launchd's minimal one"
        assert env["NJLI_NODE"].endswith("/node") and env["NJLI_NPX"].endswith("/npx")
        assert env["NJLI_FFMPEG"].endswith("/ffmpeg") and env["NJLI_FFPROBE"].endswith("/ffprobe")
        assert env["NJLI_CLAUDE_BIN"].endswith("/claude") and env["PYTHONUTF8"] == "1"
        assert d["Label"] == f"io.njli.demo.{job.name}"
        assert d["ProgramArguments"][-4:-1] == ["run", job.name, "--workspace"]
    board = plistlib.loads(bk.render_plist(ctx, golden_jobs()[-1]).text.encode("utf-8"))
    assert board["RunAtLoad"] is True and board["KeepAlive"] == {"SuccessfulExit": False}
    weekly = plistlib.loads(bk.render_plist(ctx, golden_jobs()[0]).text.encode("utf-8"))
    assert weekly["StartCalendarInterval"] == {"Weekday": 4, "Hour": 10, "Minute": 0}
    assert plistlib.loads(bk.render_plist(ctx, golden_jobs()[1]).text.encode("utf-8"))["StartInterval"] == 900


def test_a_tool_that_is_not_installed_is_simply_not_captured():
    ctx, _ = posix_ctx()
    ctx.tools = {"node": ctx.tools["node"]}
    env = plistlib.loads(bk.render_plist(ctx, golden_jobs()[0]).text.encode("utf-8"))["EnvironmentVariables"]
    assert "NJLI_NODE" in env and "NJLI_CLAUDE_BIN" not in env


# ------------------------------------------------------------------ shared

def test_every_command_calls_the_stable_runtime_with_an_absolute_workspace_and_no_dash_m():
    for make in (posix_ctx, windows_ctx):
        ctx, _ = make()
        for job in golden_jobs():
            cmd = bk.job_command(ctx, job)
            assert cmd[:2] == ctx.entry and "-m" not in cmd and "-I" not in cmd
            assert cmd[cmd.index("--workspace") + 1] == ctx.workspace
            assert "runtime" in cmd[1]


def test_task_names_are_profile_scoped():
    assert golden_jobs()[0].task_name("work") == "njli-work-build_week"
    ctx, _ = posix_ctx()
    assert bk.launchd_label("work", "board") == "io.njli.work.board"


def test_job_table_from_the_default_config(mkws):
    ws = mkws()
    names = {j.name for j in jobs_from_config(cfg_of(ws))}
    assert names == {"build_week", "research_weekly", "token_check", "doctor_weekly", "profile_review", "board"}, \
        "the default install enables exactly these six; post_due and the engagement jobs stay off"
