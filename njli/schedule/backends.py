"""Renderers for the native schedulers: Task Scheduler XML, systemd units, a crontab block, launchd plists.

Every function here is pure: given a :class:`Context` and a :class:`~njli.schedule.jobs.Job` it returns
text. Nothing touches the machine, so golden-file tests can run every backend on every OS. The
install, remove and query commands live in :mod:`njli.schedule.install`.

Every scheduled command is ``<interpreter> <runtime>/current[/njli.pyz] run <job> --workspace <abs>``;
the interpreter is the one captured at install time, never ``python -m``.
"""
from __future__ import annotations

import plistlib
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from .jobs import Job, Rule

BACKENDS = ("windows", "systemd", "cron", "launchd")
CAPTURED_TOOLS = ("node", "npx", "ffmpeg", "ffprobe", "claude")
TASK_ANCHOR = "2024-01-01"  # a Monday in the past; the first real run is the next matching moment
XML_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


@dataclass
class Context:
    """Everything a renderer needs. ``tools`` holds the absolute paths resolved at install time."""
    profile: str
    workspace: str
    entry: List[str]                     # [interpreter, <runtime>/current[/njli.pyz]]
    path_env: str = ""
    tools: Dict[str, str] = field(default_factory=dict)
    home: str = ""
    uid: int = 501
    pythonw: Optional[str] = None        # Windows: pythonw.exe next to the interpreter, if present

    @property
    def interpreter(self) -> str:
        return self.entry[0]


@dataclass
class Artifact:
    """One scheduler object: a file to write, or the text of a crontab block."""
    backend: str
    job: str
    kind: str                            # task-xml | unit-service | unit-timer | plist | cron-line
    name: str                            # task name, unit name or label
    filename: str = ""                   # file name for file-based backends
    text: str = ""


def job_command(ctx: Context, job: Job, extra: Sequence[str] = ()) -> List[str]:
    return [*ctx.entry, "run", job.name, "--workspace", ctx.workspace, *extra]


def captured_env(ctx: Context) -> Dict[str, str]:
    """Environment a minimal-PATH scheduler needs: the user's PATH, UTF-8 and the tools' absolute paths."""
    env: Dict[str, str] = {}
    if ctx.path_env:
        env["PATH"] = ctx.path_env
    env["PYTHONUTF8"] = "1"
    for tool in CAPTURED_TOOLS:
        path = ctx.tools.get(tool)
        if path:
            env["NJLI_CLAUDE_BIN" if tool == "claude" else f"NJLI_{tool.upper()}"] = path
    return env


# ------------------------------------------------------------------------- Windows

def _win_quote(arg: str) -> str:
    return subprocess.list2cmdline([arg])


def windows_action(ctx: Context, job: Job) -> Tuple[str, str]:
    """(command, arguments) for the Exec action. pythonw.exe when present: no console window."""
    exe = ctx.pythonw or ctx.interpreter
    args = " ".join(_win_quote(a) for a in job_command(ctx, job)[1:])
    return exe, args


def _iso_duration(minutes: int) -> str:
    if minutes % 60 == 0 and minutes >= 60:
        return f"PT{minutes // 60}H"
    return f"PT{minutes}M"


_WIN_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _trigger_xml(rule: Rule) -> str:
    def start(h: int, m: int) -> str:
        return f"{TASK_ANCHOR}T{h:02d}:{m:02d}:00"

    if rule.kind == "login":
        return "    <LogonTrigger>\n      <Enabled>true</Enabled>\n    </LogonTrigger>"
    if rule.kind == "interval":
        return ("    <TimeTrigger>\n"
                f"      <StartBoundary>{start(0, 0)}</StartBoundary>\n"
                "      <Enabled>true</Enabled>\n"
                "      <Repetition>\n"
                f"        <Interval>{_iso_duration(rule.interval_min)}</Interval>\n"
                "        <StopAtDurationEnd>false</StopAtDurationEnd>\n"
                "      </Repetition>\n"
                "    </TimeTrigger>")
    if rule.kind == "weekly":
        return ("    <CalendarTrigger>\n"
                f"      <StartBoundary>{start(rule.hour, rule.minute)}</StartBoundary>\n"
                "      <Enabled>true</Enabled>\n"
                "      <ScheduleByWeek>\n"
                f"        <DaysOfWeek><{_WIN_DAYS[rule.weekday or 0]} /></DaysOfWeek>\n"
                "        <WeeksInterval>1</WeeksInterval>\n"
                "      </ScheduleByWeek>\n"
                "    </CalendarTrigger>")
    return ("    <CalendarTrigger>\n"
            f"      <StartBoundary>{start(rule.hour, rule.minute)}</StartBoundary>\n"
            "      <Enabled>true</Enabled>\n"
            "      <ScheduleByDay>\n"
            "        <DaysInterval>1</DaysInterval>\n"
            "      </ScheduleByDay>\n"
            "    </CalendarTrigger>")


def render_task_xml(ctx: Context, job: Job) -> Artifact:
    name = job.task_name(ctx.profile)
    cmd, args = windows_action(ctx, job)
    limit = "PT0S" if job.long_lived else _iso_duration(max(1, job.timeout_s // 60 + 5))
    restart = ("    <RestartOnFailure>\n      <Interval>PT1M</Interval>\n      <Count>3</Count>\n"
               "    </RestartOnFailure>\n") if job.long_lived else ""
    wake = "true" if job.wake else "false"
    text = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        f'<Task version="1.4" xmlns="{XML_NS}">\n'
        "  <RegistrationInfo>\n"
        f"    <Description>{escape(f'njli {ctx.profile}: {job.name} ({job.rule.describe()})')}</Description>\n"
        f"    <URI>\\{escape(name)}</URI>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        f"{_trigger_xml(job.rule)}\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        f"    <WakeToRun>{wake}</WakeToRun>\n"
        f"    <ExecutionTimeLimit>{limit}</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        f"{restart}"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{escape(cmd)}</Command>\n"
        f"      <Arguments>{escape(args)}</Arguments>\n"
        f"      <WorkingDirectory>{escape(ctx.workspace)}</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )
    return Artifact("windows", job.name, "task-xml", name, filename=f"{name}.xml", text=text)


def windows_commands(ctx: Context, art: Artifact, xml_path: str) -> List[List[str]]:
    return [["schtasks", "/Create", "/XML", xml_path, "/TN", art.name, "/F"]]


# ------------------------------------------------------------------------- systemd

def _sd_quote(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(p) if any(c in p for c in " \t\"'\\$") else p for p in parts)


def _oncalendar(rule: Rule) -> str:
    day = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    if rule.kind == "weekly":
        return f"{day[rule.weekday or 0]} *-*-* {rule.hour:02d}:{rule.minute:02d}:00"
    return f"*-*-* {rule.hour:02d}:{rule.minute:02d}:00"


def render_systemd(ctx: Context, job: Job) -> List[Artifact]:
    unit = job.task_name(ctx.profile)
    cmd = job_command(ctx, job, ["--no-jitter"] if (job.jitter_min and job.rule.kind != "login") else [])
    env = captured_env(ctx)
    env_lines = "".join(f"Environment={shlex.quote(f'{k}={v}')}\n" for k, v in env.items())
    install = "[Install]\nWantedBy=default.target\n"
    if job.long_lived or job.rule.kind == "login":
        svc = (f"[Unit]\nDescription=njli {ctx.profile}: {job.name}\nAfter=network-online.target\n\n"
               f"[Service]\nType=simple\nWorkingDirectory={ctx.workspace}\n{env_lines}"
               f"ExecStart={_sd_quote(cmd)}\nRestart=on-failure\nRestartSec=60\n\n{install}")
        return [Artifact("systemd", job.name, "unit-service", f"{unit}.service", f"{unit}.service", svc)]
    svc = (f"[Unit]\nDescription=njli {ctx.profile}: {job.name}\n\n"
           f"[Service]\nType=oneshot\nWorkingDirectory={ctx.workspace}\n{env_lines}"
           f"ExecStart={_sd_quote(cmd)}\nTimeoutStartSec={job.timeout_s + 300}\n")
    timer = [f"[Unit]\nDescription=njli {ctx.profile}: {job.name} ({job.rule.describe()})\n\n[Timer]\n"]
    if job.rule.kind == "interval":
        timer.append(f"OnBootSec=2min\nOnUnitActiveSec={job.rule.interval_min}min\n")
    else:
        timer.append(f"OnCalendar={_oncalendar(job.rule)}\n")
    timer.append("Persistent=true\n")
    if job.jitter_min:
        timer.append(f"RandomizedDelaySec={job.jitter_min}min\n")
    timer.append(f"Unit={unit}.service\n\n[Install]\nWantedBy=timers.target\n")
    return [Artifact("systemd", job.name, "unit-service", f"{unit}.service", f"{unit}.service", svc),
            Artifact("systemd", job.name, "unit-timer", f"{unit}.timer", f"{unit}.timer", "".join(timer))]


def systemd_commands(arts: Sequence[Artifact]) -> List[List[str]]:
    cmds = [["systemctl", "--user", "daemon-reload"]]
    for a in arts:
        if a.kind == "unit-timer" or (a.kind == "unit-service" and not any(
                x.kind == "unit-timer" and x.job == a.job for x in arts)):
            cmds.append(["systemctl", "--user", "enable", "--now", a.name])
    return cmds


# ------------------------------------------------------------------------- cron

def cron_block_markers(profile: str) -> Tuple[str, str]:
    return f"# BEGIN njli:{profile}", f"# END njli:{profile}"


def _cron_time(rule: Rule) -> str:
    if rule.kind == "login":
        return "@reboot"
    if rule.kind == "interval":
        n = rule.interval_min
        if n < 60:
            return f"*/{n} * * * *"
        hours = max(1, round(n / 60))
        return f"0 */{hours} * * *"
    if rule.kind == "weekly":
        return f"{rule.minute} {rule.hour} * * {((rule.weekday or 0) + 1) % 7}"
    return f"{rule.minute} {rule.hour} * * *"


def render_cron_line(ctx: Context, job: Job) -> Artifact:
    env = captured_env(ctx)
    prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    lock = str(PurePosixPath(ctx.workspace) / "data" / "locks" / f"cron-{job.name}.lock")
    cmd = " ".join(shlex.quote(p) for p in job_command(ctx, job))
    line = (f"{_cron_time(job.rule)} cd {shlex.quote(ctx.workspace)} && {prefix} "
            f"flock -n {shlex.quote(lock)} {cmd}")
    return Artifact("cron", job.name, "cron-line", job.task_name(ctx.profile), text=line)


def render_cron_block(ctx: Context, jobs: Sequence[Job]) -> str:
    begin, end = cron_block_markers(ctx.profile)
    lines = [begin, "# Managed by `njli schedule`. Remove with `njli schedule remove`; do not edit."]
    for j in jobs:
        lines.append(f"# {j.name}: {j.rule.describe()}")
        lines.append(render_cron_line(ctx, j).text)
    lines.append(end)
    return "\n".join(lines) + "\n"


def strip_cron_block(crontab: str, profile: str) -> str:
    begin, end = cron_block_markers(profile)
    out: List[str] = []
    skipping = False
    for line in crontab.splitlines():
        if line.strip() == begin:
            skipping = True
            continue
        if skipping:
            if line.strip() == end:
                skipping = False
            continue
        out.append(line)
    text = "\n".join(out).rstrip("\n")
    return text + "\n" if text else ""


def merge_cron_block(crontab: str, ctx: Context, jobs: Sequence[Job]) -> str:
    """The user's crontab with our block replaced (or added at the end). Everything else is untouched."""
    base = strip_cron_block(crontab, ctx.profile)
    if base:
        base = base.rstrip("\n") + "\n\n"
    return base + render_cron_block(ctx, jobs)


# ------------------------------------------------------------------------- launchd

def launchd_label(profile: str, job: str) -> str:
    return f"io.njli.{profile}.{job}"


def render_plist(ctx: Context, job: Job) -> Artifact:
    label = launchd_label(ctx.profile, job.name)
    log = str(PurePosixPath(ctx.workspace) / "data" / "logs" / f"{job.name}.launchd.log")
    d: Dict[str, object] = {
        "Label": label,
        "ProgramArguments": job_command(ctx, job),
        "WorkingDirectory": ctx.workspace,
        "EnvironmentVariables": captured_env(ctx),
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "ProcessType": "Background",
    }
    rule = job.rule
    if rule.kind == "login":
        d["RunAtLoad"] = True
        d["KeepAlive"] = {"SuccessfulExit": False}
    elif rule.kind == "interval":
        d["StartInterval"] = rule.interval_min * 60
    elif rule.kind == "weekly":
        d["StartCalendarInterval"] = {"Weekday": ((rule.weekday or 0) + 1) % 7, "Hour": rule.hour,
                                      "Minute": rule.minute}
    else:
        d["StartCalendarInterval"] = {"Hour": rule.hour, "Minute": rule.minute}
    text = plistlib.dumps(d, sort_keys=True).decode("utf-8")
    return Artifact("launchd", job.name, "plist", label, filename=f"{label}.plist", text=text)


def launchd_commands(ctx: Context, art: Artifact, path: str) -> List[List[str]]:
    return [["launchctl", "bootstrap", f"gui/{ctx.uid}", path]]


def launchd_remove_commands(ctx: Context, label: str) -> List[List[str]]:
    return [["launchctl", "bootout", f"gui/{ctx.uid}/{label}"]]


# ------------------------------------------------------------------------- dispatch

def render(backend: str, ctx: Context, jobs: Sequence[Job]) -> List[Artifact]:
    if backend == "windows":
        return [render_task_xml(ctx, j) for j in jobs]
    if backend == "systemd":
        return [a for j in jobs for a in render_systemd(ctx, j)]
    if backend == "cron":
        return [Artifact("cron", "*", "cron-block", f"njli:{ctx.profile}", text=render_cron_block(ctx, jobs))]
    if backend == "launchd":
        return [render_plist(ctx, j) for j in jobs]
    raise ValueError(f"unknown backend: {backend}")
