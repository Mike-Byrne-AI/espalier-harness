### Fixed

- **`init` and `upgrade` say when another build of the same release deployed
  your tree.** A pre-release version string does not move between builds, so
  an older install of the same version rewrote a newer build's hooks and
  reported it as repairing drift. `cc/PACK_MANIFEST.txt` now names the build
  under the version (`# espalier-build:`, a digest of the files Espalier
  deploys). Where the tree was deployed by another build, `init`, `upgrade`,
  `install-ci` and `fingerprint` name both builds and the files at stake
  before they write; `init` and `upgrade` also say so on a tree stamped before
  builds were, and stamp it. They go on rather than refuse, since the version
  cannot say which build is newer.
- **`--allow-rollback` is the way past the newer-release refusal.** Where
  `cc/PACK_MANIFEST.txt` was stamped by a later release, `init`, `upgrade`,
  `install-ci` and `fingerprint` still refuse before any write; the refusal
  now names the flag, and with it the run says what it rolls back.
- **A statusline of your own is named, with the indicators it does not
  show.** The settings merge never rewrites a `statusLine` you set, so
  Espalier's `MAINT`, `STOP=`, `bp=` and freshness indicators silently
  stopped showing. `doctor`, `merge-settings` and `upgrade` now say so, and
  `tools/cc/statusline.py --segments` prints just the indicators that are on
  for you to add to your own line.
- **A seeded `CONVENTIONS.md` or `SHARP_EDGES.md` you have filled in counts
  as your documentation.** The near-empty seeded docs stayed out of the
  fingerprint after you grounded them, so they earned no docs surface. Once
  their body is yours they are read as your docs; the large seeded catalogs
  stay out as before.
