### Fixed

- **The ship driver holds a seat's second lane while its first pull request
  is open.** The Stop hook's handoff gate held a finished second lane (one
  open pull request per seat), but `tools/cc/ship.py open` only noted the
  seat's other pull request and opened the second beside it, so any forced
  handoff -- the context threshold's ask, the operator's end-of-day
  `/handoff` -- opened two at once. `open`, and so `handoff`, now holds a lane
  that has no upstream of its own while this seat has another pull request
  open: nothing is pushed, the Stop hook's hold for the lane is written so the
  gate still asks for it after the window is cleared, the handoff arms the
  own-clear with the hold, and the next window's brief says to stay on the
  branch and open the lane once that one merges or closes. A `revert/` lane,
  and a lane the dispatcher's ruling lets onto a red base, open beside it with
  a note, since the red's clearing lands first; so does a lane whose push
  already landed once, which is the named way past a hold on another seat's
  pull request. Where gh cannot list the open pull requests, the check is
  skipped and said, where it was skipped in silence.
  (`DEF-5038`)
