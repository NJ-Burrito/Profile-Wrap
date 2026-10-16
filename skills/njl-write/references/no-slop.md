# No-slop pass

The built-in pass. It always runs and needs no other skill. The gate enforces the mechanical part
(`data/banned-words/en.json`, `ar.json`, dash rules, contrast patterns); the rest is judgement you
apply before running the gate. Optional upstream humanizers can be added as extras, never required.

## What the gate already refuses

- Words and phrases on the banned lists, in English and Arabic (`gate.extra_banned` adds your own).
- Em dashes. En dashes warn.
- The contrast shape "it's not X, it's Y", "this isn't X, it's Y" (and the Arabic equivalent warns).
- Engagement bait: "Thoughts?", "Agree?", "Comment below", "Tag someone who".
- Invisible characters (zero-width space, BOM, soft hyphen).
- Links in the caption body, more than 3 hashtags, private terms, never-say terms.

## What you check by reading

Rewrite any of these. Each has a plain fix.

| Pattern | Fix |
|---|---|
| A staged opener ("Here's the thing", "Let me tell you a story") | Start with the thing |
| A one-line closer that restates the post ("And that changes everything.") | Cut it |
| A forced triad ("faster, smarter, better") | Keep the one that is true |
| A claim of importance with nothing behind it ("This is huge") | Give the fact, or cut |
| Abstract nouns where an object exists ("solutions", "landscape", "ecosystem") | Name the object |
| Hedged openers ("It's worth noting that") | State it |
| The same sentence shape three times in a row | Vary one |
| Praise for the reader or the platform | Cut |
| A moral at the end that the story did not earn | Cut or earn it |
| Bold labels in running text ("**Key takeaway:**") | Plain sentence |
| Sales language ("unlock", "supercharge", "game changer") | Say what happens |
| Inflated adjectives ("incredible", "powerful", "robust") | Use a measured word or a fact |

## Voice check

Read the caption next to two sentences from `voice.md`. If a sentence could appear in anyone's post, it
is filler. Replace it with something only this persona could say: an object, a place, a number they have
verified, a mistake they made.

## Honesty check

- No invented story, result or quote. Every claim about the persona traces to `facts.md` or the story
  bank.
- No borrowed experience: if the persona did not do it, the post does not say they did.
- If a sentence needs a figure and none is verified, rewrite the sentence without it.

## After the pass

Run `njli gate <slug>`. The pass makes the writing better; the gate proves it is traceable. A pass
without a gate run is not done.
