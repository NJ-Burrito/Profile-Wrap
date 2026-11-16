"""Desktop notifications with a log fallback. Never raises."""
from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

from .atomic import atomic_write_json
from .fsutil import append_jsonl, read_json


def _ps_escape(text: str) -> str:
    return text.replace("'", "''").replace("\r", " ").replace("\n", " ")


def _windows_toast(title: str, message: str) -> bool:
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null;"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n = $t.GetElementsByTagName('text');"
        f"$n.Item(0).AppendChild($t.CreateTextNode('{_ps_escape(title)}')) | Out-Null;"
        f"$n.Item(1).AppendChild($t.CreateTextNode('{_ps_escape(message)}')) | Out-Null;"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($t);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'Profile-Wrap').Show($toast)")
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return False
    result = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, timeout=20)
    return result.returncode == 0


def _mac_notice(title: str, message: str) -> bool:
    exe = shutil.which("osascript")
    if not exe:
        return False
    text = message.replace("\\", "\\\\").replace('"', '\\"')
    head = title.replace("\\", "\\\\").replace('"', '\\"')
    result = subprocess.run([exe, "-e", f'display notification "{text}" with title "{head}"'],
                            capture_output=True, timeout=20)
    return result.returncode == 0


def _linux_notice(title: str, message: str) -> bool:
    exe = shutil.which("notify-send")
    if not exe:
        return False
    result = subprocess.run([exe, title, message], capture_output=True, timeout=20)
    return result.returncode == 0


def notify(title: str, message: str, workspace: Optional[Path] = None, mode: str = "auto") -> str:
    """Show a notification; return the channel used: toast, osascript, notify-send or log.

    ``mode="log"`` skips the desktop channels. The event is always appended to
    ``<workspace>/data/logs/notifications.jsonl`` when a workspace is given, which the board
    shows as a banner.
    """
    channel = "log"
    if mode != "log":
        try:
            if sys.platform == "win32":
                channel = "toast" if _windows_toast(title, message) else "log"
            elif sys.platform == "darwin":
                channel = "osascript" if _mac_notice(title, message) else "log"
            else:
                channel = "notify-send" if _linux_notice(title, message) else "log"
        except (OSError, subprocess.SubprocessError):
            channel = "log"
    if workspace is not None:
        try:
            stamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            append_jsonl(Path(workspace) / "data" / "logs" / "notifications.jsonl",
                         {"at": stamp, "title": title, "message": message, "channel": channel})
        except OSError:
            pass
    return channel


# ------------------------------------------------------------------------- notify once

SEEN_REL = Path("data") / "state" / "notify-seen.json"
DEFAULT_TTL_HOURS = 12.0


def _seen_path(workspace: Path) -> Path:
    return Path(workspace) / SEEN_REL


def _read_seen(workspace: Path) -> Dict[str, float]:
    try:
        data = read_json(_seen_path(workspace), default={})
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}


def _write_seen(workspace: Path, seen: Dict[str, float]) -> None:
    try:
        atomic_write_json(_seen_path(workspace), seen)
    except OSError:
        pass


def notify_once(key: str, title: str, message: str, workspace: Path, *,
                ttl_hours: float = DEFAULT_TTL_HOURS, mode: str = "auto",
                now: Optional[float] = None) -> bool:
    """Notify unless ``key`` was already notified less than ``ttl_hours`` ago. Returns True when it notified.

    The seen-state lives in ``<workspace>/data/state/notify-seen.json`` (keys and epoch seconds). A new
    key (for example a different status) notifies at once; ``clear_notice`` forgets a key so the next
    failure notifies immediately. Never raises.
    """
    stamp = time.time() if now is None else now
    seen = _read_seen(workspace)
    last = seen.get(key)
    if last is not None and 0 <= stamp - last < ttl_hours * 3600:
        return False
    try:
        notify(title, message, workspace=workspace, mode=mode)
    except Exception:  # noqa: BLE001 - a notification never fails its caller
        return False
    seen[key] = stamp
    _write_seen(workspace, seen)
    return True


def clear_notice(workspace: Path, key_or_prefix: str, *, prefix: bool = False) -> int:
    """Forget one key (or every key starting with it). Returns how many were removed."""
    seen = _read_seen(workspace)
    gone = [k for k in seen if (k.startswith(key_or_prefix) if prefix else k == key_or_prefix)]
    if gone:
        for k in gone:
            del seen[k]
        _write_seen(workspace, seen)
    return len(gone)
