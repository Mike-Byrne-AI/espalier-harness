### Fixed

- **On an adopter's tree, `/recall` now answers "why did a hook deny or block
  me" from the hooks guide and the troubleshooting guide** (DEF-1189). Each
  deny text cites its `docs/HOOKS.md` section by heading. Recall could not
  answer that question: on an init'd Node tree it indexed four documents and
  returned the convergence-review protocol first every time.
  - **What is indexed now:** every `##` and `###` section of `docs/HOOKS.md` and
    `docs/TROUBLESHOOTING.md`, with its body, while each still carries the seed
    stamp `init` writes.
  - **Your own file is left alone:** a file of one of those names without the
    stamp is yours, not indexed as ours. Declare it under `recall_sources` to
    index it as yours.
  - **What now lands:** the write-guard and stop-gate questions get their
    section first, and "plan guard blocked my write" reaches the plan guard's
    section.
  - **What still misses, a known candidate:** "why did the plan guard deny my
    edit" and "why did the stop gate block me" lose to session_start's long
    section.
  - **Off on this repository:** its own corpus already answers hook questions,
    and indexing every seeded reference doc here moved its recall calibration.
- **What it costs:** recall answers off-topic questions with its nearest
  neighbour, as it always has on a corpus of any size. With these sections on
  an adopter's tree, "how do I bake sourdough bread" now finds a
  troubleshooting section, while "what is the capital of portugal" still finds
  nothing. On a Node tree the word "hook" can reach the harness's hook
  sections. Read a hit as the nearest match, as `/recall` says.
