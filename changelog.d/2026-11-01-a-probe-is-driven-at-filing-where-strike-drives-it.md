### Fixed

- **A ledger row's probe is driven at filing where its strike will drive it.**
  `tools/cc/ledger_row.py file` drove a new row's probe in the checkout it ran
  in, which holds `.git`, while `strike` drives it at the base in a plain
  export of the committed files with no `.git`; so a probe that read the tree
  through git filed cleanly and could be struck only with `--no-base`, giving
  up the strike's one reading of the defect where the row said it was
  (`DEF-4074`'s probe did, on 2026-11-01). `file` now drives the probe a
  second time in the export of HEAD, through the one drive the strike's base
  reading uses, and refuses a probe that prints another value there, naming
  both readings, the export's commit and the ways past (read the tree rather
  than git, commit what the probe reads, or `--no-base`, which skips the drive
  and says so). A probe the export cannot drive (a subject or input not yet
  committed, as the ledger `init` has just written is) is a printed note, as
  the strike treats it, and the probe's `verified_` stamp records where it was
  read either way. `repin` drives and refuses the same way when it changes the
  command, subject, inputs or open value. Of the 228 live probes with a
  command, two print another value in the export and two read UNRESOLVED
  there.
