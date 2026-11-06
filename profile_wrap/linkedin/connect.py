"""The guided "Connect LinkedIn" flow, shared by the desktop screen and ``profile-wrap auth connect``.

Five steps: create the developer app, add the two products, set the redirect URL, save the client id and
secret, sign in. Each step reports its own result as ``{id, state, code, params}`` where ``code`` is a key
in ``gui_assets/i18n/{en,ar}.json`` (so the screen and the terminal speak both languages from one table).

What it will not do, and tests hold it to:
* ask for, accept or store your LinkedIn sign-in details (a request that carries them is refused);
* put the client secret in any answer, message or log;
* turn on ``api_scheduled`` (opting in to API posting means ``api_click``: you still press Allow);
* claim a portal step is done when only the sign-in can prove it (the products are checked by the scopes
  the token comes back with).

Posting stays copy mode until the user opts in; nothing here is needed for copy mode.
"""
from __future__ import annotations

import datetime as _dt
import re
import socket
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import config as config_mod
from .. import i18n
from . import auth

REQUIRED_SCOPES = ("openid", "profile", "w_member_social")
STEP_IDS = ("app", "products", "redirect", "credentials", "signin")
LOOPBACK_HOSTS = ("localhost", "127.0.0.1")
CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9]{8,40}$")
CLIENT_SECRET_RE = re.compile(r"^[A-Za-z0-9_=+/.\-]{8,128}$")
PORTAL_URL = "https://www.linkedin.com/developers/apps"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"
SIGNIN_TIMEOUT_S = auth.CALLBACK_TIMEOUT_S
PASSWORD_KEYS = ("password", "passwd", "pwd", "li_password", "linkedin_password")  # profile-wrap-compliance-allow: credentials


class ConnectError(Exception):
    """A refusal the user can act on. ``code`` is an i18n key; ``message`` is the English text."""

    def __init__(self, code: str, **params: Any):
        self.code = code
        self.params = params
        super().__init__(i18n.t(code, "en", **params))


# ------------------------------------------------------------------ pure checks

def refuse_password(body: Dict[str, Any]) -> None:
    """Profile-Wrap never takes LinkedIn sign-in details, so a request carrying a secret of that kind stops here."""
    for key in body:
        if isinstance(key, str) and key.strip().lower() in PASSWORD_KEYS:
            raise ConnectError("res.creds.password_refused")


def check_client_id(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise ConnectError("res.creds.id_empty")
    if not CLIENT_ID_RE.match(text):
        raise ConnectError("res.creds.id_format")
    return text


def check_client_secret(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise ConnectError("res.creds.secret_empty")
    if not CLIENT_SECRET_RE.match(text):
        raise ConnectError("res.creds.secret_format")
    return text


def parse_redirect(uri: Any) -> Dict[str, Any]:
    """Split the redirect URL; raise ``ConnectError`` naming the first thing to fix."""
    text = uri.strip() if isinstance(uri, str) else ""
    parts = urllib.parse.urlsplit(text)
    if parts.scheme != "http":
        raise ConnectError("res.redirect.scheme")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise ConnectError("res.redirect.host", host=host or "(none)")
    try:
        port = parts.port
    except ValueError:
        port = None
    if not port:
        raise ConnectError("res.redirect.port")
    if parts.path in ("", "/"):
        raise ConnectError("res.redirect.path")
    return {"uri": text, "host": host, "port": port, "path": parts.path}


def port_free(port: int) -> bool:
    """True when the sign-in listener could bind this port on the IPv4 loopback."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def missing_scopes(scopes: Any) -> List[str]:
    have = set(str(scopes).replace(",", " ").split()) if isinstance(scopes, str) else set(scopes or [])
    return [s for s in REQUIRED_SCOPES if s not in have]


def reauth_info(cfg: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    """The 60-day re-auth date, from the stored token. Empty values before the first sign-in."""
    status = auth.token_status(auth.secrets_dir(cfg), int(cfg["linkedin"]["token_warn_days"]), now)
    out: Dict[str, Any] = {"state": status["state"], "days_left": status["days_left"], "name": status["name"],
                           "expires_on": None, "warn_from": None, "lifetime_days": auth.DEFAULT_EXPIRES // 86400}
    if status["state"] == "missing":
        return out
    try:
        expires = float(auth.load_token(auth.secrets_dir(cfg)).get("expires_at", 0))
    except (auth.AuthError, TypeError, ValueError):
        return out
    when = _dt.datetime.fromtimestamp(expires)
    out["expires_on"] = when.date().isoformat()
    out["warn_from"] = (when - _dt.timedelta(days=int(cfg["linkedin"]["token_warn_days"]))).date().isoformat()
    return out


def explain_error(message: str) -> str:
    """Map LinkedIn's or the listener's wording to one plain i18n code."""
    low = (message or "").lower()
    if "scope" in low or "unauthorized" in low:
        return "res.signin.error.scope"
    if "redirect_uri" in low or "redirect uri" in low or "redirect address" in low:
        return "res.signin.error.redirect"
    if "invalid_client" in low or "client_secret" in low or "client authentication" in low or " 401 " in low:
        return "res.signin.error.client"
    if "no answer from the browser" in low:
        return "res.signin.error.timeout"
    if "cannot listen on port" in low:
        return "res.redirect.busy"
    return "res.signin.error.other"


# ------------------------------------------------------------------ credentials

def saved_client(cfg: Dict[str, Any]) -> Dict[str, bool]:
    cid, secret = auth.read_client(auth.secrets_dir(cfg))
    return {"id": bool(cid), "secret": bool(secret), "id_valid": bool(cid and CLIENT_ID_RE.match(cid)),
            "secret_valid": bool(secret and CLIENT_SECRET_RE.match(secret))}


def save_credentials(cfg: Dict[str, Any], client_id: Any, client_secret: Any) -> None:
    """Validate both values, then store them the existing way (config dir, user-only permissions)."""
    cid = check_client_id(client_id)
    secret = check_client_secret(client_secret)
    auth.save_client(auth.secrets_dir(cfg), cid, secret)


# ------------------------------------------------------------------ the five steps

def steps(cfg: Dict[str, Any], *, now: Optional[float] = None,
          port_free_fn: Callable[[int], bool] = port_free, listening: bool = False) -> List[Dict[str, Any]]:
    """Each step's own result. ``state`` is done, todo, fix or wait; ``code`` is the message to show."""
    li = cfg["linkedin"]
    saved = saved_client(cfg)
    out: List[Dict[str, Any]] = []

    def add(step: str, state: str, code: str, **params: Any) -> None:
        out.append({"id": step, "state": state, "code": code, "params": params})

    # 1. the app: the client id is the only trace of it this machine can see
    if saved["id"] and saved["id_valid"]:
        add("app", "done", "res.app.done")
    elif saved["id"]:
        add("app", "fix", "res.creds.id_format")
    else:
        add("app", "todo", "res.app.todo")

    # 2. the products: the config must ask for them, and the token must carry them
    config_missing = missing_scopes(li.get("scopes"))
    status = auth.token_status(auth.secrets_dir(cfg), int(li["token_warn_days"]), now)
    if config_missing:
        add("products", "fix", "res.products.config_scopes", missing=", ".join(config_missing))
    elif status["state"] in ("ok", "warn", "expired"):
        try:
            token_missing = missing_scopes(auth.load_token(auth.secrets_dir(cfg)).get("scopes", ""))
        except auth.AuthError:
            token_missing = list(REQUIRED_SCOPES)
        if token_missing:
            add("products", "fix", "res.products.missing_scope", missing=", ".join(token_missing))
        else:
            add("products", "done", "res.products.done")
    else:
        add("products", "wait", "res.products.unverified")

    # 3. the redirect: a valid loopback address, and a free port to listen on
    try:
        red = parse_redirect(li.get("redirect_uri"))
    except ConnectError as exc:
        add("redirect", "fix", exc.code, **exc.params)
    else:
        if not listening and not port_free_fn(red["port"]):
            add("redirect", "fix", "res.redirect.busy", port=red["port"])
        else:
            add("redirect", "done", "res.redirect.done", uri=red["uri"], port=red["port"])

    # 4. the credentials
    if not saved["id"] and not saved["secret"]:
        add("credentials", "todo", "res.creds.todo")
    elif not saved["id"]:
        add("credentials", "todo", "res.creds.id_empty")
    elif not saved["secret"]:
        add("credentials", "todo", "res.creds.secret_empty")
    elif not saved["id_valid"]:
        add("credentials", "fix", "res.creds.id_format")
    elif not saved["secret_valid"]:
        add("credentials", "fix", "res.creds.secret_format")
    else:
        add("credentials", "done", "res.creds.done")

    # 5. the sign-in
    creds_ok = out[3]["state"] == "done"
    if status["state"] == "ok":
        add("signin", "done", "res.signin.done", name=status["name"] or "", days=int(status["days_left"] or 0))
    elif status["state"] == "warn":
        add("signin", "fix", "res.signin.soon", days=int(status["days_left"] or 0))
    elif status["state"] == "expired":
        add("signin", "fix", "res.signin.expired")
    elif not creds_ok:
        add("signin", "todo", "res.signin.blocked")
    else:
        add("signin", "todo", "res.signin.todo")
    return out


def overview(cfg: Dict[str, Any], *, now: Optional[float] = None, listening: bool = False,
             port_free_fn: Callable[[int], bool] = port_free) -> Dict[str, Any]:
    """Everything the screen needs, with no secret in it."""
    li = cfg["linkedin"]
    rows = steps(cfg, now=now, listening=listening, port_free_fn=port_free_fn)
    return {"steps": rows, "ready": all(r["state"] == "done" for r in rows),
            "redirect_uri": li.get("redirect_uri"), "scopes": list(li.get("scopes") or []),
            "products": ["Share on LinkedIn", "Sign In with LinkedIn using OpenID Connect"],
            "portal_url": PORTAL_URL, "reauth": reauth_info(cfg, now),
            "posting_mode": cfg["posting"]["mode"], "ui_language": ui_language(cfg)}


def ui_language(cfg: Dict[str, Any]) -> str:
    return i18n.normalize(cfg.get("board", {}).get("ui_language", "en"))


# ------------------------------------------------------------------ opt in to API posting

def enable_api_posting(ws: Path, now: Optional[float] = None) -> str:
    """Opt in to ``api_click``. Refused without a valid, complete sign-in. Never ``api_scheduled``."""
    cfg = config_mod.load(ws)
    state = auth.token_status(auth.secrets_dir(cfg), int(cfg["linkedin"]["token_warn_days"]), now)["state"]
    if state not in ("ok", "warn"):
        raise ConnectError("api.refused.token")
    try:
        missing = missing_scopes(auth.load_token(auth.secrets_dir(cfg)).get("scopes", ""))
    except auth.AuthError:
        missing = list(REQUIRED_SCOPES)
    if missing:
        raise ConnectError("res.products.missing_scope", missing=", ".join(missing))
    report = config_mod.set_value(ws, "posting.mode", '"api_click"')
    if report.errors:
        raise ConnectError("res.signin.error.other", detail="; ".join(str(e) for e in report.errors))
    return "api_click"


def back_to_copy_mode(ws: Path) -> str:
    report = config_mod.set_value(ws, "posting.mode", '"copy"')
    if report.errors:
        raise ConnectError("res.signin.error.other", detail="; ".join(str(e) for e in report.errors))
    return "copy"


# ------------------------------------------------------------------ the desktop sign-in session

class SignIn:
    """One sign-in at a time, run on a background thread so the page can poll it.

    ``wait`` and ``complete`` are the real ``auth`` functions unless a test passes fakes, so the state,
    the refusals and the error mapping are exercised without a network or a browser.
    """

    def __init__(self, cfg: Dict[str, Any], *, hp: Any = None,
                 open_browser: Optional[Callable[[str], Any]] = None,
                 wait: Callable[..., str] = auth.wait_for_callback,
                 complete: Callable[..., Dict[str, Any]] = auth.complete_signin,
                 timeout: float = SIGNIN_TIMEOUT_S):
        self.cfg, self.hp, self.open_browser = cfg, hp, open_browser
        self._wait, self._complete, self.timeout = wait, complete, timeout
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.state = "idle"          # idle, waiting, done, error
        self.code = ""
        self.params: Dict[str, Any] = {}
        self.url = ""

    @property
    def waiting(self) -> bool:
        return self.state == "waiting"

    def snapshot(self) -> Dict[str, Any]:
        return {"state": self.state, "code": self.code, "params": dict(self.params), "url": self.url,
                "seconds": int(self.timeout)}

    def start(self) -> Dict[str, Any]:
        with self.lock:
            if self.state == "waiting":
                raise ConnectError("res.signin.busy")
            cid, secret = auth.read_client(auth.secrets_dir(self.cfg))
            if not cid or not secret:
                raise ConnectError("res.signin.blocked")
            check_client_id(cid)
            check_client_secret(secret)
            red = parse_redirect(self.cfg["linkedin"].get("redirect_uri"))
            if not port_free(red["port"]):
                raise ConnectError("res.redirect.busy", port=red["port"])
            import secrets as _secrets

            state = _secrets.token_urlsafe(24)
            self.url = auth.authorize_url(cid, red["uri"], state, self.cfg["linkedin"]["scopes"])
            self.state, self.code, self.params = "waiting", "res.signin.waiting", {"seconds": int(self.timeout)}
            self.thread = threading.Thread(target=self._run, args=(cid, secret, red["uri"], state),
                                           name="gui-signin", daemon=True)
            self.thread.start()
            return self.snapshot()

    def _run(self, cid: str, secret: str, redirect: str, state: str) -> None:
        def announce() -> None:
            if self.open_browser is not None:
                try:
                    self.open_browser(self.url)
                except Exception:  # a headless machine: the link on the screen is enough
                    pass

        try:
            code = self._wait(redirect, state, self.timeout, on_ready=announce)
            record = self._complete(self.cfg, code, cid, secret, redirect, hp=self.hp)
        except Exception as exc:  # noqa: BLE001 - every failure becomes one plain message
            detail = str(exc).replace(secret, "[REDACTED]")[:200]
            with self.lock:
                self.state, self.code, self.params = "error", explain_error(detail), {"detail": detail}
            return
        days = max(0, int((float(record["expires_at"]) - time.time()) // 86400))
        with self.lock:
            self.state, self.code = "done", "res.signin.done"
            self.params = {"name": record.get("name") or "", "days": days}

    def join(self, timeout: float = 5.0) -> None:
        if self.thread is not None:
            self.thread.join(timeout)


# ------------------------------------------------------------------ the terminal flow

def run_guided(cfg: Dict[str, Any], *, lang: str = "en", ws: Optional[Path] = None,
               input_fn: Callable[[str], str] = input,
               secret_fn: Optional[Callable[[str], str]] = None,
               out: Callable[[str], None] = print,
               sign_in: Optional[Callable[..., Dict[str, Any]]] = None,
               port_free_fn: Callable[[int], bool] = port_free,
               hp: Any = None, now: Optional[float] = None) -> int:
    """Walk the five steps in a terminal. Returns 0 when signed in, 1 when stopped or a step failed."""
    lang = i18n.normalize(lang)

    def say(key: str, **params: Any) -> None:
        out(i18n.t(key, lang, **params))

    def pause() -> bool:
        reply = input_fn(i18n.t("cli.press_enter", lang)).strip().lower()
        if reply in ("q", "quit", "exit"):
            say("cli.stopped")
            return False
        return True

    def report(step_id: str) -> Dict[str, Any]:
        row = next(r for r in steps(cfg, now=now, port_free_fn=port_free_fn) if r["id"] == step_id)
        mark = {"done": "[ok]", "todo": "[..]", "fix": "[!!]", "wait": "[..]"}[row["state"]]
        out(f"{mark} {i18n.t(row['code'], lang, **row['params'])}")
        return row

    li = cfg["linkedin"]
    say("connect.intro")
    say("connect.nopassword")
    out("")

    say("connect.step_n", n=1, total=5)
    say("step.app.title")
    say("step.app.how")
    out(PORTAL_URL)
    if not pause():
        return 1
    out("")

    say("connect.step_n", n=2, total=5)
    say("step.products.title")
    say("step.products.how")
    for name in ("Share on LinkedIn", "Sign In with LinkedIn using OpenID Connect"):
        out("  - " + name)
    if not pause():
        return 1
    if report("products")["state"] == "fix":
        return 1
    out("")

    say("connect.step_n", n=3, total=5)
    say("step.redirect.title")
    say("step.redirect.how")
    out("  " + str(li.get("redirect_uri")))
    row = report("redirect")
    if row["state"] == "fix":
        return 1
    if not pause():
        return 1
    out("")

    say("connect.step_n", n=4, total=5)
    say("step.credentials.title")
    say("step.credentials.how")
    row = next(r for r in steps(cfg, now=now, port_free_fn=port_free_fn) if r["id"] == "credentials")
    if row["state"] != "done":
        import getpass

        try:
            cid = input_fn(i18n.t("cli.client_id_prompt", lang))
            secret = (secret_fn or getpass.getpass)(i18n.t("cli.secret_prompt", lang))
            save_credentials(cfg, cid, secret)
        except ConnectError as exc:
            out("[!!] " + i18n.t(exc.code, lang, **exc.params))
            return 1
    if report("credentials")["state"] != "done" or report("app")["state"] != "done":
        return 1
    out("")

    say("connect.step_n", n=5, total=5)
    say("step.signin.title")
    say("step.signin.how")
    if not pause():
        return 1
    run = sign_in or auth.run_auth
    try:
        run(cfg, hp=hp, input_fn=input_fn, secret_fn=secret_fn, out=out)
    except Exception as exc:  # noqa: BLE001 - one plain line, then the reason
        detail = str(exc)[:300]
        out("[!!] " + i18n.t(explain_error(detail), lang, detail=detail, port=_port_of(li)))
        return 1
    if report("signin")["state"] != "done" or report("products")["state"] != "done":
        return 1
    info = reauth_info(cfg, now)
    if info["expires_on"]:
        say("reauth.text", date=info["expires_on"], warn=info["warn_from"])
    if ws is not None and cfg["posting"]["mode"] == "copy":
        if input_fn(i18n.t("cli.enable_prompt", lang)).strip().lower() in ("y", "yes", "نعم"):
            try:
                enable_api_posting(Path(ws), now)
                say("api.done")
            except ConnectError as exc:
                out("[!!] " + i18n.t(exc.code, lang, **exc.params))
                return 1
            return 0
    say("connect.finish_cli")
    return 0


def _port_of(li: Dict[str, Any]) -> Any:
    try:
        return parse_redirect(li.get("redirect_uri"))["port"]
    except ConnectError:
        return ""
