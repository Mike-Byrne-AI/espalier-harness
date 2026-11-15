### Fixed

- **The confirm-once checkpoints now read a program a carrier runs.** A force
  push, a tag push, a clean, a discard, a kill or a recursive delete run by
  find's `-exec`, `-execdir`, `-ok` or `-okdir`, by fd's `-x` or `-X`, by GNU
  parallel, or handed to `su -c` or `script` (BSD `script`'s command after its
  file word too) drew no confirm step where its bare spelling drew one. Each
  now draws what its direct twin draws. An item a launcher finds, or reads
  from a file or stdin, is no remove operand, so the everyday
  `find . -name __pycache__ -exec rm -rf {} +` stays silent, and parallel's
  literal items read as the line it runs for each: `parallel rm -rf {} :::
  build dist` is as silent as `rm -rf build dist`, and `parallel git push
  origin {} ::: v1.2.3` asks as the tag push does. The fetch-and-execute
  checkpoint reads the same programs. The reading is a word walk, so no
  pattern is added to any call. Still unread: a launcher behind a wrapper
  switch's word value (`sudo -u app parallel ...`), a parallel switch that
  takes a value the reader does not list, parallel's items past its first
  sixteen or from more than one source, and the PowerShell tool.
