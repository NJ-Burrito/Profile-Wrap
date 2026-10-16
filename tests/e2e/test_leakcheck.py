"""leaks scan: seeded bad fixtures fail, clean trees pass, the denylist sees through encodings."""
from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from njli import leakcheck as L

# Terms and secrets are assembled at run time so this file never contains them whole.
TERM = "Fern" + "hill Cycles"
GH = "gh" + "p_" + "A1b2C3d4" * 5
APIFY = "apify" + "_api_" + "Zx9Qw8Er7Ty6"
MAIL = "jane.doe" + "@" + "gmail.com"
CDN = "https://media.lic" + "dn.com/dms/image/v2/ABC/photo.jpg?e=1999999999&v=beta&t=abcDEF123"
WINHOME = "C:" + "\\Users\\" + "jdoe\\Desktop"
POSIXHOME = "/home/" + "jdoe/projects"
LONGID = "7123456" + "789012345678"
URN = "urn:li:" + "share:" + LONGID


@pytest.fixture()
def denylist(tmp_path: Path) -> L.Denylist:
    p = tmp_path / "outside" / "deny.json"
    p.parent.mkdir()
    p.write_text(json.dumps(L.build_denylist([TERM, "Zork Quux"], salt="s3")), encoding="utf-8")
    return L.Denylist.load(p)


def tree(tmp_path: Path, files: dict[str, bytes | str]) -> Path:
    root = tmp_path / "repo"
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return root


def rules(findings) -> set[str]:
    return {f.rule for f in findings}


CLEAN = {
    "README.md": "Maya Rivera is fictional. Mail maya@example.com or hi@example.invalid.\nhttps://www.linkedin.com/in/maya-rivera-demo and urn:li:person:DEMO000000.\n",
    "njli/a.py": "x = 1\nprint('hello')\n# see /home/<name>/ and ~/projects\n",
    "docs/FONTS.md": "Licensed families are listed here: " + "Thman" + "yah.\n",
}


def test_clean_tree_passes(tmp_path):
    assert L.scan_tree(tree(tmp_path, CLEAN)) == []


@pytest.mark.parametrize(
    "name,files,expected",
    [
        ("token", {"a.txt": f"key = {GH}\n"}, "token-github"),
        ("apify", {"a.txt": f"APIFY={APIFY}\n"}, "token-apify"),
        ("email", {"a.txt": f"contact {MAIL}\n"}, "email"),
        ("signed-cdn", {"a.md": f"![x]({CDN})\n"}, "signed-cdn-url"),
        ("win-home", {"a.py": f"P = r'{WINHOME}'\n"}, "home-path"),
        ("posix-home", {"a.sh": f"cd {POSIXHOME}\n"}, "home-path"),
        ("urn", {"a.json": json.dumps({"id": URN})}, "linkedin-urn"),
        ("activity-id", {"a.txt": f"id {LONGID}\n"}, "activity-id"),
        ("tracking", {"a.md": "https://example.com/p?utm" + "_source=x\n"}, "tracking-param"),
        ("real-linkedin-url", {"a.md": "see linkedin" + ".com/in/some-real-person\n"}, "linkedin-url"),
        ("font", {"assets/f.woff2": b"wOF2\x00\x01"}, "font-binary"),
        ("font-ttf", {"f.ttf": b"\x00\x01\x00\x00"}, "font-binary"),
        ("photo", {"img/me.jpg": b"\xff\xd8\xff\xe1\x00\x10Exif\x00\x00II*\x00"}, "photo"),
        ("pyc", {"njli/__pycache__/a.cpython-312.pyc": b"\x00\x00"}, "pyc"),
        ("zipapp", {"njli.pyz": b"#!/usr/bin/env python3\nPK"}, "zipapp-committed"),
        ("env-file", {".env": "A=1\n"}, "secret-file"),
        ("token-json", {"cfg/token.json": "{}"}, "secret-file"),
        ("font-name", {"a.md": "set the font to " + "Thman" + "yah Sans\n"}, "font-name"),
        ("big", {"data.bin": b"\x00" * 1_200_000}, "big-binary"),
        ("media", {"a.png": b"\x89PNG\r\n\x1a\n\x00"}, "media-unlisted"),
        ("phone", {"a.md": "call +" + "962 7 9123 4567\n"}, "phone"),
    ],
)
def test_seeded_bad_fixture_fails(tmp_path, name, files, expected):
    found = L.scan_tree(tree(tmp_path, files))
    assert expected in rules(found), (name, found)


def test_private_term_plain(tmp_path, denylist):
    root = tree(tmp_path, {"a.md": f"We worked with {TERM} once.\n"})
    found = L.scan_tree(root, denylist=denylist)
    assert rules(found) == {"private-term"}
    assert TERM not in " ".join(f.render() for f in found)  # report never echoes the term


def test_private_term_case_underscore_and_concat(tmp_path, denylist):
    root = tree(tmp_path, {"a.py": "fernhill_cycles = 1\n", "b.py": "x = 'FernhillCycles'\n", "c.md": "FERNHILL   cycles\n"})
    found = L.scan_tree(root, denylist=denylist)
    assert {f.path for f in found if f.rule == "private-term"} == {"a.py", "b.py", "c.md"}


def test_private_term_in_unicode_escape(tmp_path, denylist):
    esc = "".join(f"\\u{ord(c):04x}" for c in TERM)
    esc_x = "".join(f"\\x{ord(c):02x}" for c in "Zork Quux")
    root = tree(tmp_path, {"a.json": json.dumps({"k": TERM}, ensure_ascii=True), "b.py": f"s = '{esc}'\n", "c.py": f"s = '{esc_x}'\n"})
    found = L.scan_tree(root, denylist=denylist)
    assert {f.path for f in found if f.rule == "private-term"} == {"a.json", "b.py", "c.py"}


def test_private_term_in_base64_hex_and_percent(tmp_path, denylist):
    b64 = base64.b64encode(f"owner: {TERM}".encode()).decode()
    b64u = base64.urlsafe_b64encode(f"x {TERM} y".encode()).decode().rstrip("=")
    hexs = TERM.encode().hex()
    pct = TERM.replace(" ", "%20")
    nested = base64.b64encode(base64.b64encode(TERM.encode())).decode()
    root = tree(tmp_path, {"a.txt": f"blob={b64}\n", "b.txt": f"{b64u}\n", "c.txt": f"h {hexs}\n", "d.txt": f"/{pct}\n", "e.txt": f"{nested}\n"})
    found = L.scan_tree(root, denylist=denylist)
    assert {f.path for f in found if f.rule == "private-term"} == {"a.txt", "b.txt", "c.txt", "d.txt", "e.txt"}


def test_private_term_in_file_name(tmp_path, denylist):
    root = tree(tmp_path, {"notes/Zork_Quux.md": "ok\n"})
    assert "private-term" in rules(L.scan_tree(root, denylist=denylist))


def test_denylist_has_no_plaintext():
    data = L.build_denylist([TERM], salt="abc")
    blob = json.dumps(data).lower()
    assert "fern" not in blob and "cycles" not in blob


def test_denylist_clean_text_passes(tmp_path, denylist):
    root = tree(tmp_path, {"a.md": "A fern on a hill, and cycles of work. Zork alone is fine.\n" + base64.b64encode(b"nothing to see here at all").decode() + "\n"})
    assert L.scan_tree(root, denylist=denylist) == []


def test_denylist_rejects_short_terms():
    with pytest.raises(ValueError):
        L.build_denylist(["ab"])


def test_allow_by_hash_waives_font_but_not_by_path(tmp_path):
    import hashlib

    data = b"OFLFONTDATA"
    root = tree(tmp_path, {"assets/ofl.woff2": data})
    sha = hashlib.sha256(data).hexdigest()
    allow = root / "release" / "leak-allow.json"
    allow.parent.mkdir()
    allow.write_text(json.dumps({"version": 1, "allow": [{"rule": "font-binary", "sha256": sha, "reason": "OFL test font"}]}))
    assert L.scan_tree(root) == []
    allow.write_text(json.dumps({"version": 1, "allow": [{"rule": "font-binary", "path": "assets/*", "reason": "x"}]}))
    with pytest.raises(L.AllowError):
        L.scan_tree(root)


def test_allow_entry_needs_reason_and_cannot_waive_private_term(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"allow": [{"rule": "email", "path": "x", "reason": ""}]}))
    with pytest.raises(L.AllowError):
        L.load_allow(p)
    p.write_text(json.dumps({"allow": [{"rule": "private-term", "path": "x", "reason": "no"}]}))
    with pytest.raises(L.AllowError):
        L.load_allow(p)


def test_allow_by_path_waives_text_rule(tmp_path):
    root = tree(tmp_path, {"tests/fx.txt": f"x {MAIL}\n", "release/leak-allow.json": json.dumps({"allow": [{"rule": "email", "path": "tests/*", "reason": "fixture"}]})})
    assert L.scan_tree(root) == []


def _zip(members: dict[str, bytes | str], shebang: bytes = b"") -> bytes:
    buf = io.BytesIO()
    buf.write(shebang)
    with zipfile.ZipFile(buf, "a") as z:
        for k, v in members.items():
            z.writestr(k, v)
    return buf.getvalue()


def test_dist_scans_wheel_sdist_zipapp(tmp_path, denylist):
    out = tmp_path / "dist"
    out.mkdir()
    (out / "pkg-0.1-py3-none-any.whl").write_bytes(_zip({"njli/ok.py": "x=1\n", "njli/leak.py": f"t='{GH}'\n"}))
    (out / "njli.pyz").write_bytes(_zip({"__main__.py": f"# {TERM}\n", "f/a.woff2": b"wOF2"}, shebang=b"#!/usr/bin/env python3\n"))
    tgz = io.BytesIO()
    with tarfile.open(fileobj=tgz, mode="w:gz") as tf:
        data = f"mail {MAIL}\n".encode()
        ti = tarfile.TarInfo("pkg-0.1/README.md")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    (out / "pkg-0.1.tar.gz").write_bytes(tgz.getvalue())
    found = L.scan_dist([out], denylist=denylist)
    got = {(f.rule, f.path.split("!")[0]) for f in found}
    assert ("token-github", "pkg-0.1-py3-none-any.whl") in got
    assert ("private-term", "njli.pyz") in got
    assert ("font-binary", "njli.pyz") in got
    assert ("email", "pkg-0.1.tar.gz") in got
    assert not any(f.rule == "zipapp-committed" for f in found)  # a zipapp is a legitimate dist artefact


def test_dist_clean_and_missing(tmp_path):
    z = tmp_path / "ok.zip"
    z.write_bytes(_zip({"a.txt": "fine\n"}))
    assert L.scan_dist([z]) == []
    assert rules(L.scan_dist([tmp_path / "nope.whl"])) == {"dist-missing"}


def test_dist_nested_archive(tmp_path):
    inner = _zip({"leak.txt": f"{GH}\n"})
    z = tmp_path / "outer.zip"
    z.write_bytes(_zip({"inner.zip": inner}))
    assert "token-github" in rules(L.scan_dist([z]))


def run_cli(*args, env=None, cwd=None):
    import os

    e = {**os.environ, "PYTHONUTF8": "1"}
    e.pop(L.ENV_DENYLIST, None)
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "njli.leakcheck", *args], capture_output=True, text=True, env=e, cwd=cwd or Path(__file__).resolve().parents[2], encoding="utf-8")


def test_cli_exit_codes_tree_and_dist(tmp_path, denylist):
    bad = tree(tmp_path, {"a.txt": f"{GH}\n"})
    r = run_cli("scan", "--tree", str(bad))
    assert r.returncode == 1 and "token-github" in r.stdout and GH not in r.stdout
    good = tmp_path / "good"
    good.mkdir()
    (good / "a.txt").write_text("fine\n")
    assert run_cli("scan", "--tree", str(good)).returncode == 0
    z = tmp_path / "x.zip"
    z.write_bytes(_zip({"p.txt": f"{MAIL}\n"}))
    assert run_cli("scan", "--dist", str(z)).returncode == 1
    z.write_bytes(_zip({"p.txt": "ok\n"}))
    assert run_cli("scan", "--dist", str(z)).returncode == 0


def test_cli_denylist_env_flag_and_required(tmp_path, denylist):
    deny_path = tmp_path / "outside" / "deny.json"
    root = tree(tmp_path, {"a.md": f"{TERM}\n"})
    assert run_cli("scan", "--tree", str(root)).returncode == 0  # no denylist: skipped with a warning
    assert run_cli("scan", "--tree", str(root), "--require-denylist").returncode == 2
    assert run_cli("scan", "--tree", str(root), "--denylist", str(deny_path)).returncode == 1
    assert run_cli("scan", "--tree", str(root), env={L.ENV_DENYLIST: str(deny_path)}).returncode == 1


def test_cli_denylist_build_roundtrip(tmp_path):
    terms = tmp_path / "terms.txt"
    terms.write_text(f"# private\n{TERM}\n", encoding="utf-8")
    out = tmp_path / "d.json"
    assert run_cli("denylist-build", str(terms), str(out)).returncode == 0
    root = tree(tmp_path, {"a.md": f"{TERM}\n"})
    assert run_cli("scan", "--tree", str(root), "--denylist", str(out)).returncode == 1


def test_git_tree_ignores_gitignored_files(tmp_path):
    root = tree(tmp_path, {".gitignore": "*.woff2\n", "a.txt": "ok\n", "f.woff2": b"wOF2"})
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert L.scan_tree(root) == []
    (root / "g.woff2").write_bytes(b"x")  # still ignored
    assert L.scan_tree(root) == []
    (root / "h.ttf").write_bytes(b"x")  # not ignored
    assert rules(L.scan_tree(root)) == {"font-binary"}
