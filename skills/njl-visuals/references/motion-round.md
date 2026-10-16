# The motion round

A mode of this skill for raising the bar on a motion standard or a template, not for routine posts. The user approves by eye before
any rollout.

## Stages (each leaves a file)

1. **Devil.** One reviewer attacks the current standard and the current best GIF: ranked objections, the assumption each attacks, the
   cheapest test that settles it (`agents/council-devil.md`). Output: `reviews/motion/devil-<date>.md`.
2. **Research.** Look up what keeps people watching a looping silent clip; cite sources; separate evidence from taste. Output:
   `research/motion/<date>.md`.
3. **Trials.** Build two or three variants of the same message in separate `videos/trial-*` projects, each with a different idea (for
   example kinetic type, an editorial cut, a camera move). Same copy, same canvas. Run the same metrics on each.
4. **Council.** Seats score each trial on a thumbnail contact sheet and the metrics: motion director, growth, scrolling reader,
   language and region seat for any Arabic, and the design seat at 360 px. Scores and reasons, not adjectives.
5. **Pick and merge.** Take the winner, or a hybrid of the top two. Write the verdict to `reviews/motion/council-<date>.md`.
6. **Promote.** Only the Lead changes the library or the rules. After a library change: bump `VERSION`, run `njli motion status`, then
   `njli motion upgrade --queued-only`. A post whose re-render fails any gate keeps its previous files (the upgrade restores them).

## Rules of the round

- Machine steps run once; one fix and one re-render per failed gate.
- A hold, a dim, or any "still" frame is judged by the metrics with the logged hold excluded, never by eye alone.
- Trials are private: never shown to the audience, never repeated for polish.
- A model that fails a stage is not retried at the same tier with the same prompt.
