"""The user's own installed ``claude`` CLI, through the existing ``claude_runner`` (unchanged).

Subscription users keep working without an API key. No credential is read or stored here: the
runner starts the unmodified binary with its scrubbed environment. Text only: the worker gets one read-only tool (the runner needs
a non-empty list) and may change nothing but a scratch folder.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .base import Provider, ProviderError, Result, schema_instruction

SCRATCH = "data/provider-scratch/**"


class ClaudeCodeProvider(Provider):
    supports_tools = True  # the claude CLI runs its own tool loop under claude_runner's rules

    def __init__(self, *args: Any, workspace: Optional[Path] = None,
                 cfg: Optional[Mapping[str, Any]] = None, exe: Optional[Sequence[str]] = None,
                 **kw: Any):
        super().__init__(*args, **kw)
        self.workspace = Path(workspace) if workspace else None
        self.cfg = cfg
        self.exe = exe

    def api_key(self) -> str:
        return ""  # never needed

    def _complete(self, system: str, messages: List[Dict[str, str]],
                  json_schema: Optional[Mapping[str, Any]], max_tokens: int, timeout: float) -> Result:
        from .. import claude_runner as cr, config as cfgmod
        if self.workspace is None:
            raise ProviderError("config", "the claude-code provider needs a workspace "
                                "(run it inside one or pass --workspace)")
        cfg = self.cfg if self.cfg is not None else cfgmod.load(self.workspace)
        parts = [system] if system else []
        if json_schema:
            parts.append(schema_instruction(json_schema))
        parts += [f"{m['role'].upper()}: {m['content']}" for m in messages]
        res = cr.run_worker(self.workspace, cfg, job="provider-complete", kind="comment",
                            prompt="\n\n".join(parts), allow=[SCRATCH], tools=["Read"], timeout=timeout,
                            exe=self.exe)
        if not res.ok:
            kind = "missing_key" if res.status == cr.NO_CLAUDE else "bad_response"
            raise ProviderError(kind, f"claude-code: {res.status}: {(res.err or '').strip()[:300]}")
        return Result(text=res.text, usage={})
