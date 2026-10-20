"""server.json against the official registry schema, listing files, README ownership line, and the
real stdio transport (the way `claude mcp add` launches the server)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import jsonschema
import pytest

MCP = Path(__file__).resolve().parents[1]
ROOT = MCP.parent


def test_server_json_validates_against_the_registry_schema():
    schema = json.loads((MCP / "tests" / "data" / "server.schema.json").read_text(encoding="utf-8"))
    doc = json.loads((MCP / "server.json").read_text(encoding="utf-8"))
    assert doc["$schema"] == schema["$id"]
    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(doc, schema)
    pkg = doc["packages"][0]
    assert pkg["registryType"] == "pypi" and pkg["identifier"] == "profile-wrap-mcp"
    assert pkg["transport"]["type"] == "stdio"
    assert pkg["version"] == doc["version"]            # pinned, same as the package


def test_server_json_matches_pyproject_and_readme():
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib
    proj = tomllib.loads((MCP / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    doc = json.loads((MCP / "server.json").read_text(encoding="utf-8"))
    assert proj["name"] == doc["packages"][0]["identifier"] and proj["version"] == doc["version"]
    readme = (MCP / "README.md").read_text(encoding="utf-8")
    assert f"mcp-name: {doc['name']}" in readme
    assert doc["name"] == "io.github.NJ-Burrito/profile-wrap-mcp"
    assert "not affiliated with linkedin" in readme.lower().replace("**", "")
    assert "linkedin" not in proj["name"].lower() and not proj["name"].startswith(("claude", "anthropic"))


def test_listing_files_are_valid():
    glama = json.loads((MCP / "glama.json").read_text(encoding="utf-8"))
    assert glama["maintainers"] == ["NJ-Burrito"]
    smithery = (MCP / "smithery.yaml").read_text(encoding="utf-8")
    assert "type: stdio" in smithery and "profile-wrap-mcp" in smithery
    assert (ROOT / "docs" / "MCP.md").is_file()


def test_real_stdio_server_lists_tools_and_answers(env):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "profile_wrap_mcp", "--workspace", str(env.ws)],
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(MCP)]), "PYTHONUTF8": "1"})

    async def go():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                res = await s.call_tool("review_state", {})
                return {t.name for t in tools.tools}, res
    names, res = asyncio.run(asyncio.wait_for(go(), 60))
    assert "post_allowed" in names and len(names) == 9
    assert not res.is_error
