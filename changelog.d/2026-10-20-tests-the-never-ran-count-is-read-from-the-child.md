### Fixed

- **The crashed-controller row reads its never-ran count from the child, not
  from a pin.** `tests/test_xdist_never_ran.py`'s
  `test_the_never_ran_line_is_written_where_no_summary_ran` pinned
  `2 of 6 selected tests never ran`, but how many crashed tests xdist reports
  before the probe's controller raise depends on the runner's timing: it read
  `4 of 6` on a macOS portability leg and `3 of 6` on `main`'s post-merge proof
  on Linux, which held every lane's landing until the job was re-run. The row
  now counts the tests the child reported from the child's own progress marks
  (the terminal reporter writes one as each report arrives) and asserts the
  never-ran line is the six less those, exactly, with at most four reported;
  `TestTheProgressMarksCountTheReports` pins the witness over the three shapes
  read so far. The never-ran plugin is unchanged.
