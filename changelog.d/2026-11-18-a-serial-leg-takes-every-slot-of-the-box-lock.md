### Added

- **A box can hold more than one test tier at once.** The box lock's slot
  count is one whole number in the file beside the lock, `<lock>.slots`
  (`tools/cc/_json_safe.py::box_lock_slots`, the one reader): absent, the box
  has one slot, the lock file itself, as before; slot k from 2 on is
  `<lock>.slot<k>`; anything but a whole number from 1 to 8 reads as one slot
  and says so on stderr. The count belongs to the box, not to a seat's
  environment, so one stray export cannot put two tiers on a small machine. A
  parallel line takes the first free slot, and waits at slot 1 unless another
  parallel line holds it. Any run at one worker (the files kept off parallel
  load for their wall-clock budgets, and `-n auto` that resolves to one) and
  the guard cost census take every slot, in order, keeping each as it comes,
  so they do not run beside another seat's pool; while one waits for the rest, its record in the
  slots it holds says so, a parallel line waits behind it rather than taking
  a free slot beside it, and it is never handed the past-the-ceiling stop
  command. A nested run reads its inherited pair over every slot before it
  tries one, so it passes through its parent's slot and takes none. Every
  line in `<lock>.log` names its `slot` (`every` for a one-worker hold) and
  the box's `slots`. The speed bump's kill reading reads every slot's holder,
  so a kill of the tree on slot 2 is nudged as one on slot 1 was. To let two
  seats run tiers at once on a machine with room for both: first bring every
  checkout that runs tiers there onto this change (an older one locks the
  lock file alone, whatever the count), point every seat at one lock path
  (relaunch from a shell that exports no other), then write `2` into
  `<lock>.slots`, for the default path with
  `python -c "import pathlib; pathlib.Path.home().joinpath('.espalier', 'espalier-box.lock.slots').write_text('2')"`.
  On a box of several slots a hold's log lines pair by the run's pid.
