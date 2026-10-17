### Fixed

- **Three gaps in the edit-time sync advisories (Espalier's own tree).** An
  edit of the vendored `espalier/_vendor/cc/` copy is now told that the next
  `scripts/sync_vendor_cc.py` run discards it, and which `tools/cc/` file to
  edit instead. The warning that an edit inside a generated doc region will
  be discarded no longer counts against the session's advisory budget, so it
  is still said past the fifth advisory; it is said once a session and names
  every generated region and its source. And after a context compaction each
  sync advisory may be said once more, since the compaction dropped the
  context it was said into; a resume clears nothing.
