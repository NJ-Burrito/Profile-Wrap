# Calendar format

`strategy/calendar.json` is the source of truth; `strategy/calendar.md` is generated from it by
`profile-wrap calendar render-md` and is never edited. The schema is `schema/calendar.schema.json`.

```json
{
  "schema_version": 1,
  "entries": [
    {
      "date": "2026-11-03",
      "slug": "2026-11-03-retries-hide-bugs",
      "lang": "en",
      "format": "gif",
      "pillar": "P1",
      "title": "A retry is not a fix",
      "angle": "Show the retry loop masking the real failure",
      "hook": "Your retry is hiding a bug.",
      "claims": ["F03"],
      "status": "planned",
      "time": "10:07",
      "time_reason": "",
      "series": "",
      "pair": "",
      "open": false
    }
  ]
}
```

| Field | Rule |
|---|---|
| `date` | `YYYY-MM-DD`, in the configured timezone. A blocked holiday is an error. |
| `slug` | unique; lowercase letters, digits and hyphens. The draft folder is `drafts/<slug>/`. |
| `lang` | one of `persona.languages`. |
| `format` | `text`, `slides`, `gif`, `image`, `document`, `multi_image`; a warning if it is not in `posting.formats_enabled`. |
| `status` | `planned`, `built`, `posted`, `skipped`, `blocked`. |
| `claims` | fact ids; each must exist and be `verified` while the entry is live. |
| `time` | optional `HH:MM`. Without it, `build-week` picks a stable minute (`time_auto: true`). A time outside the window needs `time_reason`. |
| `pair` | the slug (or pair id) of the other half of a bilingual pair. Only a pair may share a date. |
| `open` | `true` on a placeholder made by `profile-wrap calendar fill`. `build-week` skips open slots. |

## Commands

| Command | Does |
|---|---|
| `profile-wrap calendar add --date D --slug S --title T ...` | adds one entry under a lock; refuses a duplicate slug |
| `profile-wrap calendar validate [--json]` | unique slug and date, status, language, window, holidays, claim ids, weekly counts |
| `profile-wrap calendar render-md` | writes `calendar.md` |
| `profile-wrap calendar fill --weeks N [--dry-run]` | open slots on `posting.weekdays`, skipping holidays and filled days, rotating pillars |
| `profile-wrap plan windows` | each day's window, holiday blocks and shifts |
| `profile-wrap plan slots <slug or date>` | the posting time `build-week` would use |
| `profile-wrap build-week [--days 8-14] [--slug S] [--dry-run] [--cleanup S]` | builds drafts for planned entries 8 to 14 days ahead |

## Statuses over time

`planned` (you wrote it) then `built` (a draft exists and passed the gate) then `posted` (the ledger has it).
`blocked` waits for a fact or a decision; `skipped` is a deliberate no. Only `planned`, briefed entries are
built. A failed build leaves the entry `planned` with the failure in `work/build.log`; `profile-wrap build-week
--cleanup <slug>` moves the half-made folders to `work/trash/` so the entry can be built again.

## Writes are atomic

Every write goes to a temporary file and replaces the calendar in one step, under a lock. A crash or a second
command at the same moment cannot leave half a calendar.
