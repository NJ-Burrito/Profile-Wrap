# Timing recipe

How `njli plan recipe` turns "where my audience is" into a posting window, and how far to trust it.
The data is in `data/timing-recipe.json`; this page is the reading guide.

Not advice about how to win. These are studies of other people's accounts. Your own numbers, once you have
enough posts, beat them.

## What the studies say

| Source | Grade | What it found |
|---|---|---|
| Buffer, 4.8 million posts, published 2026-09-09, times normalised to each poster's local time | A | Weekday peak 15:00 to 20:00. Best slots Wednesday 16:00, Friday 15:00 and 16:00. Best days Wednesday, then Thursday, then Friday; weakest Monday, then Tuesday. Mornings (06:00 to 11:00) lower. Most accounts start to see results at 2 to 5 posts a week; consistency beats bursts. |
| Sprout Social, summarised by third parties (the summaries disagree on the sample size) | B | Tuesday 11:00 to 17:00, Wednesday 11:00 to 16:00, Thursday 13:00 to 17:00. The original was not fetched. |
| Hootsuite, via secondary blogs | C | 08:00 to 09:00 on Tuesday and Wednesday. Older, and the original was not found. |

Consensus: Tuesday to Thursday are good, weekends are weak, and the 2026 Buffer data sits later in the day
than the older studies. The grade is the grade of the evidence for *that finding*, not a promise it will hold
for you.

## The recipe

1. Take `locale.audience_regions`. `njli plan recipe --list` shows the region ids and their timezones.
2. Take a slice of the audience's afternoon: **15:30 to 18:59 audience-local**. It is 3 hours 29 minutes wide,
   inside the Buffer peak and around its best slots, and narrow enough that two consecutive daily posts stay
   at least 20 hours apart whatever minute each gets.
3. Convert the slice to your timezone for each region on the same date.
4. With several regions, use the part they share when it is at least 60 minutes wide. Otherwise the recipe
   uses the first region you listed and tells you, so list the audience that matters most first.
5. If the slice crosses midnight in your timezone, it is moved to stay inside one day and the tool warns you.
6. Apply it with `njli plan recipe --audience <ids> --apply`, which sets `posting.window` (both ends at once,
   because the width rule is checked on the pair) and `locale.audience_regions`. The config validator checks
   the width.

Example: you are in Lisbon, your audience is in the Gulf and the Levant. Gulf 15:30 to 18:59 is 12:30 to
15:59 Lisbon time; the Levant slice is 13:30 to 16:59. The overlap, 13:30 to 15:59, is the window.

## What it does not know

- Whether the datasets, dominated by accounts with large audiences, hold for a small one.
- Whether they hold for Arabic-language audiences: no source splits by language.
- How the feed treats a post the API schedules versus one posted by hand. Nobody has published this.
- Daylight saving: the slice is converted on today's date. Re-run the recipe after a clock change.

## Why the default window is different

The default `posting.window` is 09:00 to 12:29 in your own timezone. It is a conservative placeholder that
works before you say where your audience is, not a recommendation. Run the recipe once you have set your
regions.

## What to do with your own data

After ten or more posts, export your analytics and look at impressions by hour in `metrics/`. If your own best
hours differ from this recipe, move the window to them. A sample of under ten posts shows nothing; say so
rather than reading a pattern into it.
