# A stale egg-info makes a packaging gate verify the previous config

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "A Stale egg-info Makes a Packaging Gate Verify the Previous Config"

> **This entry previously claimed the opposite mechanism** — that
> `include-package-data` ships any git-tracked file under a package, making the
> `[tool.setuptools.package-data]` globs "belt-and-suspenders, not load-bearing"
> and a drop-the-glob earn-the-red "structurally impossible." That is wrong, and
> the correction is the point of this entry. The filename still carries the old
> slug so existing citations resolve.

**What it is:** setuptools caches the package's file list in
`*.egg-info/SOURCES.txt` and **reuses it on later builds even after the config
that produced it is gone**. Delete a `package-data` glob, rebuild without
clearing the egg-info, and the wheel still contains the files the deleted glob
used to match. Every payload assertion passes — against the *previous* config.

**Why the old explanation was believable:** the observation was real. A wheel
built with the `assets/task-packs/*.md` glob removed genuinely did still contain
`espalier/assets/task-packs/CLAUDE.md`. Only the *cause* was misattributed. The
check that was skipped is the one that separates the two explanations: clear the
egg-info and rebuild.

**Driven** (same tree, same setuptools, only the two variables moved):

| `*.egg-info` | glob | `SOURCES.txt` lists it | in wheel |
|---|---|---|---|
| cleared | present | yes | yes |
| **kept from the previous build** | **deleted** | **yes (stale)** | **yes** — the illusion |
| cleared | deleted | no | **no** |

**Why "git-tracked" was never the mechanism:** `include-package-data` does
default to True under declarative `pyproject` config, but it does not mean "ship
git-tracked files." It means *also ship whatever the sdist file list assigns to
this package* — and that list comes from `MANIFEST.in` plus any **file-finder
plugin**. Git is visible to setuptools only through such a plugin
(`setuptools-scm` and friends). This repo has none:

```
$ python -c "from importlib.metadata import entry_points; \
    print(list(entry_points(group='setuptools.file_finders')))"
[]
```

With no file finder and no `MANIFEST.in` rule matching `espalier/assets/**/*.md`
(it carries `recursive-include espalier *.py *.typed`), the `package-data` globs
are the **only** channel shipping those assets. They are load-bearing: delete one
and the asset stops shipping.

**Consequences — the inverse of what this entry used to say:**

- The asset globs are **the gate**, not a redundant belt. A dropped glob is a
  real, shippable defect.
- A "drop the glob → the asset stops shipping" **earn-the-red is entirely
  possible**, and should be demanded of any packaging contract. This is *not* an
  instance of the earn-the-red platform ceiling; it was a dirty workspace.
- A gate that cannot fail is worse than no gate, because it reads as coverage.
  `tests/test_wheel_payload.py::_clean_build_dir` removed `build/` but not
  `*.egg-info/`, so **every** payload contract in that module was verifying
  against a cached manifest. It now removes both — and the one home is
  `espalier/artifact_parity.py::clear_stale_packaging_state`, called from
  every build path (`artifact_parity.build_wheel`, the release matrix's sdist
  and wheel stages, and `_clean_build_dir` itself, now a delegate), with a
  stdlib twin in `scripts/wheel_smoke.py::_clear_stale_packaging_state` pinned
  by driven parity in `tests/test_wheel_smoke.py`.

**How to avoid it:** before trusting any packaging measurement, remove `build/`
**and** `*.egg-info/`. Both are gitignored, so cleaning them needs no restore.
Then drive the real artifact — a non-editable install into a fresh environment,
run from a directory outside the repo so the source tree cannot shadow the
installed package.

**The general shape:** a build system that caches a derived file list will answer
questions about the *cached* inputs, not the current ones. Treat any build
artifact directory as part of the experiment's state — an uncleaned one silently
converts "does this config work?" into "did the previous config work?", and the
answer looks identical.
