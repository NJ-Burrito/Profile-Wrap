---
description: Check this machine and the workspace; explains every WARN or FAIL with the fix for your OS.
argument-hint: "[--online] [--fix]"
---
Run `"${CLAUDE_PLUGIN_ROOT}/bin/njli" doctor $ARGUMENTS` and show the PASS/WARN/FAIL table.
For every WARN or FAIL, say in one line what it stops working and give the hint printed for this
operating system. If the stable runtime has drifted after a plugin update, offer `njli runtime sync`.
Do not install anything yourself unless the user says yes.
