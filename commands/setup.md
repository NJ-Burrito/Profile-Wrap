---
description: Set up Profile-Wrap (interview, workspace, config), or try the demo first.
argument-hint: "[demo | express | section name]"
---
Use the `pw-setup` skill to set up Profile-Wrap for the user.

- No argument: ask whether they want to try the demo first, an express setup (7 questions) or the
  full interview.
- `demo`: run `"${CLAUDE_PLUGIN_ROOT}/bin/profile-wrap" init --demo` and explain the output.
- `express`: run the express path of the skill.
- A step name (who, privacy, facts, voice, brand, cadence, models, consent): re-enter that step on the
  existing workspace with `profile-wrap init --section <name> --answers <file>`.

Ask every question through AskUserQuestion, in batches of at most 4. Start with `profile-wrap doctor`.
Arguments: $ARGUMENTS
