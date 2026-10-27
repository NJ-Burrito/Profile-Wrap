"""OAuth on the user's own LinkedIn developer app, and the token file.

* 3-legged flow with a localhost redirect: state check, 3-minute timeout, IPv4 fallback when IPv6
  is off, ``--paste-redirect`` for SSH and containers.
* Least scope: ``openid profile w_member_social``.
* The client id and secret and the token live in the config dir only (user-only permissions).
  The client secret is typed into a hidden prompt, never echoed, never written to the workspace.
* There is no refresh token for an ordinary app: the user runs ``profile-wrap auth`` again before expiry.
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .. import paths
from ..fsutil import read_json, write_secret
from ..http import HostPolicy, HttpError, request

CLIENT_FILE = "linkedin.env"
TOKEN_FILE = "token.json"
OAUTH_BASE = "https://www.linkedin.com"
AUTHORIZE_PATH = "/oauth/v2/authorization"  # profile-wrap-compliance-allow: api-endpoint
TOKEN_PATH = "/oauth/v2/accessToken"  # profile-wrap-compliance-allow: api-endpoint
DEFAULT_EXPIRES = 5184000  # 60 days, what LinkedIn issues today
CALLBACK_TIMEOUT_S = 180


class AuthError(Exception):
    """Sign-in cannot continue; the message says what to do next."""


# ------------------------------------------------------------------ files

def secrets_dir(cfg: Dict[str, Any]) -> Path:
    return paths.config_dir(cfg.get("profile_id", "default"))


def read_client(cfg_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    """(client_id, client_secret) from the environment, else from ``linkedin.env``."""
    cid, secret = os.environ.get("LINKEDIN_CLIENT_ID"), os.environ.get("LINKEDIN_CLIENT_SECRET")
    file = Path(cfg_dir) / CLIENT_FILE
    if file.is_file():
        for line in file.read_text(encoding="utf-8-sig").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"')
            if key == "LINKEDIN_CLIENT_ID" and not cid:
                cid = value
            if key == "LINKEDIN_CLIENT_SECRET" and not secret:
                secret = value
    return cid or None, secret or None


def save_client(cfg_dir: Path, client_id: str, client_secret: str) -> Path:
    text = f"LINKEDIN_CLIENT_ID={client_id}\nLINKEDIN_CLIENT_SECRET={client_secret}\n"
    return write_secret(Path(cfg_dir) / CLIENT_FILE, text)


def load_token(cfg_dir: Path) -> Dict[str, Any]:
    file = Path(cfg_dir) / TOKEN_FILE
    if not file.is_file():
        raise AuthError("no access token yet: run 'profile-wrap auth' (see docs/linkedin-app-setup.md)")
    try:
        tok = read_json(file)
    except ValueError as exc:
        raise AuthError(f"{file} is not valid JSON ({exc}); run 'profile-wrap auth' again") from exc
    if not isinstance(tok, dict) or not tok.get("access_token") or not tok.get("author"):
        raise AuthError(f"{file} is incomplete; run 'profile-wrap auth' again")
    return tok


def save_token(cfg_dir: Path, tok: Dict[str, Any]) -> Path:
    return write_secret(Path(cfg_dir) / TOKEN_FILE, json.dumps(tok, indent=2) + "\n")


def token_status(cfg_dir: Path, warn_days: int = 10, now: Optional[float] = None) -> Dict[str, Any]:
    """{state: missing|ok|warn|expired, days_left, name, message}. Never raises."""
    try:
        tok = load_token(cfg_dir)
    except AuthError as exc:
        return {"state": "missing", "days_left": None, "name": None, "message": str(exc)}
    left = (float(tok.get("expires_at", 0)) - (now if now is not None else time.time())) / 86400
    if left <= 0:
        return {"state": "expired", "days_left": round(left, 1), "name": tok.get("name"),
                "message": "the access token has expired: run 'profile-wrap auth'"}
    if left <= warn_days:
        return {"state": "warn", "days_left": round(left, 1), "name": tok.get("name"),
                "message": f"the access token expires in {left:.1f} days: run 'profile-wrap auth' soon"}
    return {"state": "ok", "days_left": round(left, 1), "name": tok.get("name"),
            "message": f"token valid for {left:.0f} more days"}


def require_token(cfg_dir: Path) -> Dict[str, Any]:
    """The token, or ``AuthError`` when missing or expired."""
    tok = load_token(cfg_dir)
    if float(tok.get("expires_at", 0)) <= time.time():
        raise AuthError("the access token has expired: run 'profile-wrap auth'")
    return tok


# ------------------------------------------------------------------ flow

def authorize_url(client_id: str, redirect_uri: str, state: str, scopes: Any) -> str:
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "state": state, "scope": " ".join(scopes)})
    return f"{OAUTH_BASE}{AUTHORIZE_PATH}?{query}"


def parse_redirect(text: str, state: str) -> str:
    """The authorization code from a pasted redirect URL (or bare query string)."""
    text = text.strip()
    query = urllib.parse.urlsplit(text).query if "?" in text or "://" in text else text
    values = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
    if "error" in values:
        raise AuthError(f"LinkedIn refused the request: {values.get('error_description', values['error'])}")
    if values.get("state") != state:
        raise AuthError("the state value does not match: start 'profile-wrap auth' again (do not reuse an old link)")
    if not values.get("code"):
        raise AuthError("no authorization code in the pasted text")
    return values["code"]


class _QuietServer(http.server.HTTPServer):
    """HTTPServer without the slow host-name lookup, and never sharing a port with another listener."""

    # POSIX SO_REUSEADDR only skips TIME_WAIT (it never shares a live listener); on Windows it would, so keep it off there.
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


def _make_server(port: int, handler: type) -> http.server.HTTPServer:
    """The sign-in listener binds the IPv4 loopback only, never "::" or "0.0.0.0" (nothing on the LAN can reach it)."""
    return _QuietServer(("127.0.0.1", port), handler)


def wait_for_callback(redirect_uri: str, state: str, timeout: float = CALLBACK_TIMEOUT_S,
                      on_ready: Optional[Callable[[], None]] = None) -> str:
    """Listen on the redirect port until the browser returns; verify state; return the code."""
    parts = urllib.parse.urlsplit(redirect_uri)
    port = parts.port or 80
    want_path = parts.path or "/"
    got: Dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            url = urllib.parse.urlsplit(self.path)
            if url.path != want_path:
                self.send_response(404)
                self.end_headers()
                return
            got.update({k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and return to the terminal.")

        def log_message(self, *args: Any) -> None:
            return

    try:
        srv = _make_server(port, Handler)
    except OSError as exc:
        raise AuthError(f"cannot listen on port {port} for the redirect ({exc}). "
                        "Use 'profile-wrap auth --paste-redirect' instead.") from exc
    srv.timeout = 0.5
    deadline = time.monotonic() + timeout
    try:
        if on_ready:
            on_ready()
        while "code" not in got and "error" not in got:
            if time.monotonic() > deadline:
                raise AuthError(f"no answer from the browser within {int(timeout)} seconds. "
                                "Run 'profile-wrap auth' again, or use --paste-redirect.")
            srv.handle_request()
    finally:
        srv.server_close()
    return parse_redirect(urllib.parse.urlencode(got), state)


def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str,
                  hp: Optional[HostPolicy] = None, timeout: float = 30.0) -> Dict[str, Any]:
    form = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": code, "client_id": client_id,
        "client_secret": client_secret, "redirect_uri": redirect_uri}).encode("ascii")
    try:
        resp = request("POST", f"{OAUTH_BASE}{TOKEN_PATH}", body=form, timeout=timeout, hp=hp,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    except HttpError as exc:
        raise AuthError(f"sign-in failed: {exc}") from exc
    if not resp.ok:
        detail = resp.text()[:300]
        raise AuthError(f"LinkedIn answered {resp.status} to the token request: {detail}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise AuthError("LinkedIn returned an unreadable token answer") from exc
    if not data.get("access_token"):
        raise AuthError("LinkedIn returned no access token")
    return data


def prompt_client(cfg_dir: Path, input_fn: Callable[[str], str] = input,
                  secret_fn: Optional[Callable[[str], str]] = None) -> Tuple[str, str]:
    """Ask for the app's client id and secret (hidden prompt) and store them in the config dir."""
    import getpass

    if not sys.stdin.isatty() and secret_fn is None:
        raise AuthError(
            "the client id and secret are missing. Put LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET "
            f"in {Path(cfg_dir) / CLIENT_FILE} (see docs/linkedin-app-setup.md), or run 'profile-wrap auth' "
            "in a terminal to be asked.")
    cid = input_fn("LinkedIn app client id: ").strip()
    secret = (secret_fn or getpass.getpass)("LinkedIn app client secret (hidden): ").strip()
    if not cid or not secret:
        raise AuthError("both the client id and the client secret are needed")
    save_client(cfg_dir, cid, secret)
    return cid, secret


def run_auth(cfg: Dict[str, Any], *, paste_redirect: bool = False,
             open_browser: Callable[[str], Any] = webbrowser.open,
             input_fn: Callable[[str], str] = input,
             secret_fn: Optional[Callable[[str], str]] = None,
             hp: Optional[HostPolicy] = None, version: Optional[str] = None,
             callback_timeout: float = CALLBACK_TIMEOUT_S,
             out: Callable[[str], None] = print) -> Dict[str, Any]:
    """Run the whole sign-in and save the token. Returns the stored token record."""
    from . import api  # local import: api imports this module's token helpers

    li = cfg["linkedin"]
    cfg_dir = secrets_dir(cfg)
    cid, secret = read_client(cfg_dir)
    if not cid or not secret:
        cid, secret = prompt_client(cfg_dir, input_fn, secret_fn)
    import secrets as _secrets

    state = _secrets.token_urlsafe(24)
    redirect = li["redirect_uri"]
    url = authorize_url(cid, redirect, state, li["scopes"])
    if paste_redirect:
        out("Open this link in a browser on any machine, press Allow, then paste the full address "
            "the browser ends on (it may show an error page; that is fine):\n" + url)
        code = parse_redirect(input_fn("Pasted address: "), state)
    else:
        def announce() -> None:
            out("Opening the LinkedIn consent page. If no browser opens, use this link:\n" + url)
            try:
                open_browser(url)
            except Exception:  # a headless machine: the printed link is enough
                pass
        code = wait_for_callback(redirect, state, callback_timeout, on_ready=announce)
    data = exchange_code(code, cid, secret, redirect, hp=hp)
    expires_in = int(data.get("expires_in", DEFAULT_EXPIRES))
    access = data["access_token"]
    client = api.Client(access, version or api.default_version(cfg), hp=hp,
                        timeout=float(li.get("timeout_s", 30)))
    me = client.userinfo()
    record = {"access_token": access, "expires_at": time.time() + expires_in,
              "author": f"urn:li:person:{me['sub']}", "name": me.get("name"),
              "scopes": data.get("scope", " ".join(li["scopes"])), "created": time.time()}
    save_token(cfg_dir, record)
    out(f"Signed in as {me.get('name')}. The token is valid for {expires_in // 86400} days.")
    return record


__all__ = ["AuthError", "run_auth", "token_status", "load_token", "require_token", "secrets_dir",
           "authorize_url", "parse_redirect", "wait_for_callback"]
