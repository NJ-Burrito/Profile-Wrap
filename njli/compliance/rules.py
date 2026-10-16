"""Rule table for `njli compliance lint`.

Each rule: id, compiled regex, a hint, and optional path conditions. The
vendor rule is waived only inside a file named automation-landscape.md, and
api.linkedin.com may appear only under njli/linkedin/. Any other deliberate
mention (for example a warning that the package never reads a password) is
marked on the same or the previous line with

    njli-compliance-allow: <rule-id>[, <rule-id>]

in whatever comment syntax the file uses. Each use is reviewed by a human.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern
    hint: str
    only_in: str | None = None          # rule applies only to paths with this prefix
    except_in: tuple[str, ...] = ()     # path prefixes where the rule is waived
    except_names: tuple[str, ...] = ()  # file names where the rule is waived


def _r(p: str) -> re.Pattern:
    return re.compile(p, re.I)


RULES: tuple[Rule, ...] = (
    Rule("credentials", _r(r"\bli_at\b|\bJSESSIONID\b|\bvoyager\b|\bpasswords?\b|\bcookies?\b|\bsession[_ -]?(?:cookie|token|id)\b"),
         "no password, cookie or session handling"),
    Rule("login-path", _r(r"/login\b|/checkpoint\b|\buas/login"),
         "no login or checkpoint flows"),
    Rule("messaging", _r(r"/messaging\b|/conversations\b|/voyagerMessaging"),
         "no messaging endpoints"),
    Rule("invitations", _r(r"/invitations\b|/growth/normInvitations"),
         "invitations API is partner-only; Connect is always human"),
    Rule("form-fill", _r(r"\bpage\.fill\(|\.press_sequentially\(|\bfill_form\b|\bform_fill\b|\bedit_profile\b|\bprofile_edit\b|\bupdate_profile\b"),
         "no profile-edit or form-fill code"),
    Rule("ua-rotation", _r(r"fake_useragent|user[_-]?agents?[_-]?(?:rotat|pool|list|cycle|random)|random\.choice\([^)]*user[_-]?agent"),
         "no user-agent rotation"),
    Rule("evasion-wording", _r(r"\blooks?[ _-]human\b|\bundetectable\b|\bundetected\b|\bbypass(?:es|ed|ing)?\b|\bevad(?:e|es|ing)[ _-]detection\b"),
         "automation is never disguised"),
    Rule("vendor", _r(r"\b(?:Publora|Pixfaro|Unipile)\b|\bgptzero\b|originality\.ai"),
         "unsupported vendors appear only in automation-landscape.md",
         except_names=("automation-landscape.md",)),
    Rule("api-host", _r(r"api\.linkedin\.com"),
         "only njli/linkedin/ may reach the LinkedIn API", except_in=("njli/linkedin/",)),
)

# Automation library plus linkedin.com in one file.
AUTOMATION_LIB = _r(r"\b(?:selenium|playwright|puppeteer|webdriver|pyppeteer)\b")
LINKEDIN_DOMAIN = _r(r"linkedin\.com")

# Inside njli/linkedin/ only these endpoint paths exist; socialActions only in the extra.
ENDPOINT = re.compile(r"/(?:v2|rest)/[A-Za-z][A-Za-z0-9/_-]*")
ALLOWED_ENDPOINTS = ("/v2/userinfo", "/rest/posts", "/rest/images", "/rest/documents")
EXTRA_ONLY = re.compile(r"socialActions", re.I)
LINKEDIN_PKG = "njli/linkedin/"

PRAGMA = re.compile(r"njli-compliance-allow:\s*([A-Za-z0-9_, -]+)")

SCAN_DIRS = ("njli", "skills")
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv"}
SKIP_PREFIXES = ("njli/compliance/",)   # the rule table cannot lint itself
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sh", ".ps1", ".js", ".mjs", ".ts", ".html", ".css", ".cfg", ".ini", ".tmpl", ".j2"}
