# Growth evidence

What Profile-Wrap ships as a starting point for reach advice, with the grade of each item
(scale: `docs/references/evidence-scale.md`). This file is short on purpose: it lists only what has a source
recorded in this repository. Where a source could not be verified, the entry says so.

These are studies of other people's accounts. They are not promises, and your own numbers beat them once you
have ten or more posts.

## Posting time and frequency

| Id | Source | Grade | Finding | Retrieved |
|---|---|---|---|---|
| buffer-2026-09 | Buffer, "Best time to post on LinkedIn", 4.8 million posts, published 2026-09-09, times in each poster's local time. https://buffer.com/library/best-time-to-post-on-linkedin/ | A | Weekday peak 15:00 to 20:00. Best slots Wednesday 16:00, Friday 15:00 and 16:00. Best days Wednesday, Thursday, Friday; weakest Monday, Tuesday. Mornings (06:00 to 11:00) lower. Most accounts start to see results at 2 to 5 posts a week; consistency beats bursts. | 2026-10-16 |
| sprout-secondary | Sprout Social, as summarised by a third party. https://socialk.it/en/best-time-to-post/linkedin | B | Tuesday 11:00 to 17:00, Wednesday 11:00 to 16:00, Thursday 13:00 to 17:00. The summaries disagree on the sample size. The original report was not fetched. | 2026-10-16 |
| hootsuite-secondary | Hootsuite, via secondary blogs. No URL recorded; the original was not found. | C | 08:00 to 09:00 on Tuesday and Wednesday. Older, and earlier in the day than the 2026 Buffer data. | 2026-10-16 |

Origin of these rows: `data/timing-recipe.json` and `docs/references/timing-recipe.md`. They were recorded there
on the retrieval date above. They have not been re-fetched for this file; before you quote one in a post, re-read
the source, add it to `research/stats.md` and verify it yourself.

## Not covered by a verified source

Profile-Wrap makes no evidence claim, and a seat or skill must label advice on these `INFERRED` or `opinion`:

- Hook length. The default `gate.hook_target` of 40 characters and `hook_max` of 210 are product settings, not
  findings. No study is recorded for them here.
- Hook type, emoji use, caption length, first-hour engagement, and format (text, slides, GIF) effects. No source
  recorded; benchmarks found online for these conflict or rest on unstated samples.
- Whether the timing data holds for small accounts or for Arabic-language audiences. No source splits by language.
- How the feed treats a post scheduled through the API versus one posted by hand. Nobody has published this.

To add a finding: read the primary source, record the URL, publication date, sample and retrieval date, grade it
with the scale, and add a row above. Do not add a figure you have not opened the source for.
