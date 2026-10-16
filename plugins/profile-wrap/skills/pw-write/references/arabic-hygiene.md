# Arabic hygiene

Applies when `meta.lang` includes `ar`. The gate runs the mechanical checks on every text surface
(caption, first comment, alt text, slides, video). The rest is for the writer and the language seat of
the council.

## What the gate checks

| Check | Fails on | Fix |
|---|---|---|
| Persian letters | U+067E, U+0686, U+0698, U+06AF, U+06A9, U+06CC (peh, tcheh, jeh, gaf, Persian kaf, Persian yeh) | Use the Arabic letters: kaf U+0643 and yeh U+064A |
| Tatweel | U+0640 | Remove it; do not stretch words |
| Bidi controls | LRM, RLM, ALM, embeddings, isolates (U+200E, U+200F, U+061C, U+202A-202E, U+2066-2069) | Remove them; fix direction by rewording |
| Latin comma | `,` after an Arabic letter | Use the Arabic comma U+060C |
| Latin question mark | `?` after Arabic text | Use U+061F |
| Latin semicolon | `;` after Arabic text (warns) | Use U+061B |
| Mixed numerals | Arabic-Indic and ASCII digits in one text (warns) | Pick one system for the whole text |

Arabic-Indic and Persian digits are normalised before the claim-bound number check, so "٣٠ دقيقة" is
proven by a fact with `30 دقيقة`. A fact for an Arabic post carries the Arabic unit word in its
`numbers` cell, and the post uses the same word (plural endings are ignored only for English).

## Writing notes

- **Modern Standard Arabic**, plain and short. Technical terms stay in English where the audience uses
  them ("API", "dashboard"), written in Latin letters inside the Arabic sentence.
- **Hamza and taa marbuta.** Check أ إ آ ء and ة ه at the end of words. A spell-check pass catches
  most; the language seat catches the rest.
- **No word-for-word translation** of an English post. Rewrite the hook so it works in Arabic.
- **Direction.** Keep one language per line where you can. A Latin word at the start of an Arabic line
  can flip the punctuation side; move it inside the sentence.
- **Hashtags** count toward the limit of three. Use a hashtag the audience actually searches.
- **Emoji** at the start of an Arabic line appear on the right. Keep to one per line.
- **Numbers and units.** Use the same unit word in the post as in the fact. Do not put a figure in
  words ("ثلاثون"); the gate warns on number words it cannot check.

## Bilingual pairs

The pair is the unit. Write both together, cite the same claims, gate both. When one side changes
after review, change the other in the same pass. A pair where one side is stale is worse than the
original error.

## Council

Brief `council-language-voice` for every Arabic draft. It reads for hamza, taa marbuta, Persian
letters, tatweel, numerals, punctuation, direction, and for whether the Arabic reads naturally to the
audience regions in `config/profile-wrap.json` (`locale.audience_regions`).
