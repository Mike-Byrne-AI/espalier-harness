### Fixed

- **The ReDoS file's two scaling arms now read the per-call cost inside each
  window they judge** (DEF-2002). The PowerShell body arm and the walker arm in
  the ReDoS test file (tests/test_redos.py) subtract the cost of a near-empty call from every
  sample. That cost used to be the floor of three such calls read back to back
  before the first window, and both windows were judged net of it. So one
  slowdown over those three calls raised what both windows subtracted, and a
  linear consumer read as a red:
  - super-linear on two windows;
  - or, on the PowerShell arm, a half-cap sample under the sample floor, which
    blames the host for being too fast.

  Driven on the Air with a linear stand-in at a 30 ms per-call cost slowed 1.5
  times over those calls: red 5 of 5 on both arms at 20 and 24 ms net (4.9 ->
  24.9 ms on the walker), and never at 40.
  - **The shape:** each window times the zero payload at its two ends, one
    sample each, and is judged net of the floor of the two. A floor is a
    minimum, so a slowdown raises it only by covering the whole window, which
    raises every sample with it.
  - **What did not change:** the ratios, the floors and the ceilings. The
    PowerShell arm's worst case is two windows of eight calls at the
    3400 ms alarm, 54.4 s against pytest's 60 s. Three zero samples a window,
    the shape the row was filed with, would have read 61.2 s.
    `test_the_ps_body_scaling_arm_cannot_outlast_the_per_test_timeout` now
    counts the calls on the arm's longest path rather than multiplying a
    literal, and reads the verdict's structure (two window calls, no loop), so
    a path its stand-in does not reach cannot add calls unseen.
  - **The PowerShell arm's under-floor red names its cause**, by the walker's
    DEF-926 rule. A per-call cost above what is left of the sample now reads
    as a slow or loaded host, with "re-run". It used to read as a box much
    faster than the floors' host. A red also names the floor of the window it
    rests on, and an overrun names the call that overran.
  - **What is left:** two spikes landing exactly on one window's two zero
    samples still raise that window's floor alone.
    - On the PowerShell arm at 20 ms net, that is an under-floor red on the
      first window, which is not asked again; it now names the per-call cost.
    - On the walker, the same spikes can skip a quadratic consumer as swamped.

    A slowdown over a window's six pair calls, with clean zero ends, still
    pulls a quadratic's ratio toward 1. That is unchanged from before, and it
    matters on a host whose per-call cost is near the net sample.
