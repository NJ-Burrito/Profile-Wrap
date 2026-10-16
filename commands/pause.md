---
description: Pause posting, comment drafting or everything. Every job and API call checks the flag first.
argument-hint: "[--posting | --comments | --all]  (or: resume)"
---
Run `"${CLAUDE_PLUGIN_ROOT}/bin/njli" pause $ARGUMENTS`. With no argument everything is paused.
To undo, run `"${CLAUDE_PLUGIN_ROOT}/bin/njli" resume $ARGUMENTS`. Jobs that find the flag exit with
code 4 and do nothing. Tell the user exactly what is paused and how to resume.
