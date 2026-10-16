---
description: Set up nj-linkedin (interview, workspace, config), or try the demo first.
argument-hint: "[demo | express | section name]"
---
Use the `njl-setup` skill to set up nj-linkedin for the user.

- No argument: ask whether they want to try the demo first, an express setup (7 questions) or the
  full interview.
- `demo`: run `"${CLAUDE_PLUGIN_ROOT}/bin/njli" init --demo` and explain the output.
- `express`: run the express path of the skill.
- A step name (who, privacy, facts, voice, brand, cadence, models, consent): re-enter that step on the
  existing workspace with `njli init --section <name> --answers <file>`.

Ask every question through AskUserQuestion, in batches of at most 4. Start with `njli doctor`.
Arguments: $ARGUMENTS
