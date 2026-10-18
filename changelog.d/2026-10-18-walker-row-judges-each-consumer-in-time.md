### Fixed

- **The walker scaling row now stops and reds with its readings before
  pytest's per-test timeout can kill it** (DEF-5023). The ReDoS file's walker
  scaling row (tests/test_redos.py) judges five consumers in one test, so a
  label where every consumer is swamped still reds rather than skips. Each
  consumer takes up to two windows of calls capped at 8.8 s. That is 704 s at
  the ceiling against the 60 s timeout, and the warm call had no cap at all.

  Driven on the Air with each consumer's calls spun to 8.5 s, the row was
  killed at 61 s, and the whole report was "worker 'gw0' crashed while running
  ...": no consumer, no ratio, no reading.
  - **Now:** a stop check runs before every capped call, the warm call
    included, and the warm call is under the alarm too. A call starts only
    while one ceiling still fits in a budget taken from pyproject's timeout:
    one ceiling and a 5 s margin under it, 46.2 s of 60. No call starts after
    37.4 s, against healthy labels of up to 10.3 s on the full tier's serial
    cells.
  - **The red:** once the budget would run out, the row names:
    - the consumer and window in flight, and the samples that window took;
    - its first window's reading, when it stopped in the second;
    - each finished consumer's whole reading, and the consumers not reached,
      in the row's order;
    - the cause the readings point to. It reads as a slow host when every
      reading is linear or swamped and no call of the window in flight came
      within half the ceiling, and
      as a regressed consumer otherwise.

    The same drive now reds at 43 s with those readings.
  - **The cost, named in the red:** one consumer regressed toward its ceiling
    leaves the ones after it unjudged in that run.
  - **One reader for the timeout:** the suite contract, the PowerShell body
    arm's timeout pin and the new budget all read the timeout through
    tests/_pytest_ini.py, which reads only the pytest table.
