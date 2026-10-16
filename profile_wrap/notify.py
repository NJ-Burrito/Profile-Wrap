"""Desktop notifications with a log fallback. Never raises."""
from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .fsutil import append_jsonl


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
