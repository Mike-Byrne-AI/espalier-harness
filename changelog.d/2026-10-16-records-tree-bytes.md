### Fixed

- **The landing check's pending-rows test passes on a Windows host.** The
  test plants a parked Session Log row by feeding git a tree listing as text.
  A Windows pipe rewrites each line ending, so every name in the listing
  gained a carriage return, and the planted row sat under no session-log
  directory. The test now feeds git bytes. The product's own records writer
  already passed git arguments, so it was never affected.
