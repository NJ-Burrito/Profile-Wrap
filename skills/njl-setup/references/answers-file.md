# The answers file

`njli init --answers answers.json --yes` builds a workspace from this file. It must match
`schema/answers.schema.json` (unknown keys fail). Only `schema_version` and `who` (with `name`,
`languages` and `goal`) are required; everything else falls back to the safe defaults.

```json
{
  "schema_version": 1,
  "where": { "profile_id": "default" },
  "who": {
    "name": "Alex Example",
    "handle": "alex-example-demo",
    "role": "Independent data analyst",
    "niche": "Reporting for small teams",
    "audience": "Team leads",
    "audience_regions": ["Europe"],
    "languages": ["en", "ar"],
    "primary_language": "en",
    "timezone": "Europe/Lisbon",
    "goal": "authority",
    "pillars": [
      { "id": "P1", "name": "Teach", "share": 0.5 },
      { "id": "P2", "name": "Proof of work", "share": 0.5 }
    ]
  },
  "privacy": { "private_terms": ["Example Employer Ltd"], "never_say": [], "sensitive_rules": [] },
  "facts": [
    { "claim": "Cut the weekly report from 4 hours to 1 hour", "number": "4 hours; 1 hour",
      "source": "my own timesheets, 2026 Q2" }
  ],
  "voice": { "style_preset": "plain", "samples": ["A past post ..."] },
  "brand": {
    "font_source": "user_files",
    "fonts": {
      "display": { "family": "My Licensed Sans", "files": ["~/fonts/MyLicensedSans-Bold.otf"] },
      "text": { "family": "My Licensed Sans", "files": ["~/fonts/MyLicensedSans-Regular.otf"] },
      "arabic": { "family": "My Licensed Sans", "files": ["~/fonts/MyLicensedSans-Arabic.otf"] },
      "licence_note": "Licensed to me; used for images only."
    },
    "palette_mode": "per_post",
    "identity": { "enabled": true, "name": "Alex Example", "role": "Analyst", "photo": null,
                  "signature": "typed" }
  },
  "cadence": { "per_week": 3, "comment_daily_cap": 3, "connect_weekly_slots": 3 },
  "models": { "mode": "tiered", "auth": "login" },
  "options": { "git_commit": true }
}
```

Notes
- Do not put `consent` in a file you wrote on the user's behalf. Acknowledgements are typed by the
  user (`njli config ack <action>`).
- `facts` rows are written as `draft` through the facts package. They count for nothing until the
  user verifies them in a terminal.
- Values above a ceiling (for example `per_week: 9`) make `init` stop with a message; they are never
  clamped.
- `njli init --section who --answers who.json` re-enters one step on an existing workspace.
