### Fixed

- **The ReDoS file's two scaling arms now read the per-call cost inside each
  window they judge** (DEF-2002). The PowerShell body arm and the walker arm in
  `tests/test_redos.py` subtract the cost of a near-empty call from every
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
    literal.
