### Fixed

- **A catch-up after the handoff no longer holds the own-clear on `HEAD
  moved`.** The handoff armed the marker at HEAD, the worker tick's `ship.py
  catch-up` pulled the server's merge of the base (or merged it here and
  pushed), and the own-clear mod held the clear on `HEAD moved since the
  handoff (that handoff re-arms the marker)` while nothing was ahead to hand
  off, so no handoff came and the window sat at its threshold until a re-arm
  by hand (a worker window, 2026-10-31: 3 h 33 min with its next job
  assigned). `tools/cc/ship.py catch-up` now re-arms the marker at the new
  head on both of its paths once the move landed, with the brief, how the
  handoff ended and the record the mod wrote kept and the move on the record
  (`rearmed_from`, `rearmed_by`, `rearmed_at`); `ship.py arm` re-arms the
  same way over a marker whose head moved with the lane on origin, instead
  of refusing; the mod's hold text names both verbs.
