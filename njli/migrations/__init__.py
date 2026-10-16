"""Idempotent, dry-runnable workspace migrations (``NNNN_name.py``).

Each migration module defines:
  DESCRIPTION     one line
  TOUCHES_POLICY  True when it changes a safety setting (the user is asked, with a diff)
  plan(ctx)       list of human-readable changes it would make; empty means nothing to do
  apply(ctx)      make the changes; must be safe to run twice
  FILES           optional list of workspace-relative files to back up first
"""
