### Fixed

- **A slow session start gives a short banner instead of none.** Claude Code
  cancels a SessionStart hook past its 15 s timeout and keeps none of its
  output, so a slow start opened the session with no banner at all, and the
  session read as one whose hooks had not loaded. The network reads were
  budgeted; the local work around them was not. Measured on a Windows box: 13
  of 95 starts cancelled, and on a snapshot clone one start ran 36 s. The hook
  now cuts itself at 13 s after it loads. It prints a short banner naming the
  phase it was in, says the hooks are loaded, and keeps the lines it had
  already read. Each cut leaves one `sessionstart_failed_open_wall_cut` record,
  which `/status --log` counts. The catch-up and the network reads now end
  two and a half seconds before the cut. (`DEF-3015`)
