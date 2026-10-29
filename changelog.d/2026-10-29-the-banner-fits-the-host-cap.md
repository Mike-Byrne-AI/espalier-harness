### Fixed

- **The SessionStart banner fits the host's cap on hook context.** Claude Code
  caps one hook context string at 10,000 characters and, past it, saves the
  text to a file and hands Claude a 2,000-character preview it is not asked to
  read past (`docs/external/cc-hook-protocol.md`), while the banner's outer
  ceiling was 16,000 bytes, so a seat with long orders, mail and a long goal
  could open on a preview of its own banner. The banner is now built under
  9,500 characters counted as the host counts (UTF-16 units), with
  `main()`'s backstop cutting to the same figure. The per-run header lines
  (the sessions, the pull requests, the mail, the orders, ...) share one pool
  of 320 characters each: a long line rides whole on what the absent and short
  ones leave, and past the pool the longest are cut, by whole rows, keeping the
  first row, the last row, the mail's note on whose text it is, and every
  count as `and N more`. The reinject payloads are cut to 1,000 together and
  the `Memory:` identity line to 400. The blueprint takes what the body leaves,
  health block included, at most 3,000 (6,000 for the compact banner's
  decisions), down to 400 and then to its header line, and only then is the
  body clipped. A `BANNER HEALTH` block names every cut and yield, each tenant
  against its budget and the headroom, and on a clip the characters lost and
  what to shorten: `cc/GOAL.md` when the goal is past its soft budget, else
  the largest tenant's file. The goal's 4,500-byte hard cap is unchanged. The
  standing-principles index is one summary line (the count, and where the
  titles and bodies are).
