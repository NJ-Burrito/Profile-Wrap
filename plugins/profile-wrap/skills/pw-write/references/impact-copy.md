# Impact copy

A caption style for posts that report a result. Use it when `voice.md` says `style: impact_copy`.
Original text, not a quotation of any author.

## The pattern

```text
<Bold anchor: the thing that changed, 3 to 8 words>
<separator>
<Outcome: one sentence with one true number>
<One line on how, or on what you would do differently>
<One specific closing question, or nothing>
```

- **Anchor.** A plain noun phrase that names the change: "One page replaced the weekly report."
  Not a slogan, not a question.
- **Separator.** One blank line, or a single short rule line made of a character the persona already
  uses. Do not use an em dash as the separator.
- **Outcome with one true number.** Exactly one figure, from a verified fact you cite in
  `meta.claims`, with its unit: "The weekly review now takes 30 minutes." If there is no verified
  number, write the outcome without one. Do not soften an invented figure into "about" or "nearly".
- **How.** One or two short lines. The real step, in the order it happened.
- **Close.** A question only the reader can answer, or none.

## Checks before the gate

- Can the reader say what changed after the first line? If not, rewrite the anchor.
- Is the number the outcome, and not the setup? Move it to the outcome line.
- Is every claim something the persona did or saw? Cut anything borrowed from another case.
- Would the post still read as true with the number removed? If not, the number is carrying a claim
  the text does not support.

## Example (fictional persona, no figures)

> One page replaced the weekly report.
>
> The team opened it every Monday. The old one sat unread.
>
> I kept the chart and dropped the table.
>
> Which report did your team stop reading?

With a verified fact F01 (`30 minutes`) the outcome line becomes: "The weekly review now takes 30
minutes." and `meta.claims` holds `["F01"]`.
