# Slots and windows

## The window

`posting.window` (default 09:00 to 12:29, in `locale.timezone`) is the span of the day in which posts go out.
Config validation rejects a window wider than 24 hours minus `posting.min_gap_hours` minus half an hour. With
the defaults that is 3 hours 30 minutes. The width rule is what lets consecutive daily posts stay at least
`min_gap_hours` apart whatever minute each one gets.

`profile-wrap plan recipe --audience gulf,levant` suggests a window from where the audience is. Read
`docs/references/timing-recipe.md` first: it is built on studies of other accounts and has known gaps.

## The minute: `spread_time`

Each slug gets a stable minute inside the window:

- never on a round 5-minute mark;
- never the same minute as another post within `posting.spread.no_repeat_days` days (the ledger and the
  calendar are both checked);
- far enough from the neighbouring days' posts to keep `posting.min_gap_hours` plus 15 minutes for the
  scheduler's start lag, counted in real time so a daylight saving change cannot shorten it;
- the same every time for the same slug and the same neighbours.

This spreads posts across the audience's hours and avoids a post at the same second as everything else. It is
not a way to look like a person at a keyboard: every ledger row records the automation mode that produced it.

When no minute fits (a very narrow window, a long gap), the rules are relaxed in a fixed order (repeat,
window, round mark, gap) and `profile-wrap plan slots` and `build-week` show which one, so you can widen the window or
move a post.

## Holidays

`config/holidays.json` blocks dates and can shift the window (the Ramadan presets move the window to the
evening). A shifted window is checked and used per day. A day after a shift may get a minute outside its
normal window, because the gap to the evening post wins; the plan says so.

## Overrides

A calendar `time` wins over the spread. It must fit that day's window, or carry a `time_reason` the validator
accepts. The 12-hour floor and the one-post-per-run rule in `policy.py` apply to every post whatever the
calendar says.
