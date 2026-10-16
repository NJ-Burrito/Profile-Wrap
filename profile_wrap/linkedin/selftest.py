"""``profile-wrap selftest [comments]``: read-only checks. Nothing is ever posted.

``selftest`` checks the token, the API version, the member lookup and the redirect set-up.
``selftest comments`` makes one non-posting probe (an invalid body aimed at an id that cannot
exist) and stores the result; see ``social_extra.probe`` for how to read it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..http import HttpError
from . import api, auth, social_extra, versions


def _check(name: str, ok: Optional[bool], detail: str) -> Dict[str, Any]:
    return {"name": name, "result": "PASS" if ok else ("WARN" if ok is None else "FAIL"),
            "detail": detail}


def run_selftest(ws: Path, cfg: Dict[str, Any], what: Optional[str] = None,
                 client: Optional[api.Client] = None) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    li = cfg["linkedin"]
    cfg_dir = auth.secrets_dir(cfg)
    status = auth.token_status(cfg_dir, int(li.get("token_warn_days", 10)))
    checks.append(_check("token", {"ok": True, "warn": None}.get(status["state"], False),
                         status["message"]))
    version: Optional[str] = None
    try:
        version, warns = versions.resolve(cfg)
        checks.append(_check("api version", True if not warns else None,
                             version + ("; " + "; ".join(warns) if warns else "")))
    except versions.VersionError as exc:
        checks.append(_check("api version", False, str(exc)))
    redirect = str(li.get("redirect_uri", ""))
    checks.append(_check("redirect uri",
                         redirect.startswith(("http://localhost", "http://127.0.0.1")),
                         f"{redirect} (must be registered on the app's Auth tab exactly)"))
    if status["state"] in ("ok", "warn") and version:
        try:
            tok = auth.load_token(cfg_dir)
            use = client or api.Client(tok["access_token"], version, hp=api.host_policy(cfg),
                                       timeout=float(li.get("timeout_s", 30)))
            me = use.userinfo()
            same = f"urn:li:person:{me['sub']}" == tok.get("author")
            checks.append(_check("member lookup", same,
                                 "the token belongs to the stored member" if same
                                 else "the token belongs to a different member than token.json says"))
            if what == "comments":
                result = social_extra.probe(use, ws)
                checks.append(_check("comments probe",
                                     None if result["result"] == "unknown"
                                     else result["result"] == "reachable",
                                     f"{result['result']} ({result['status']}): {result['note']}"))
                if not social_extra.installed():
                    checks.append(_check("comments extra", None,
                                         "the comments-api extra is not installed; "
                                         "the result is informational"))
        except (auth.AuthError, api.ApiError, HttpError) as exc:
            checks.append(_check("member lookup", False, str(exc)))
    elif what == "comments":
        checks.append(_check("comments probe", False, "needs a valid token and API version first"))
    failed = [c for c in checks if c["result"] == "FAIL"]
    return {"summary": "FAIL" if failed else "PASS", "checks": checks,
            "probe_only": what == "comments"}
