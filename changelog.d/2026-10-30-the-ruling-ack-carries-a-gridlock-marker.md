### Fixed

- **A gridlock ruling's ack opens with `gridlock:`, and the seat-day census
  counts its marker words where a text opens with them.** The dispatcher
  brief (`tools/cc/seat.py::SELF_HOST_GRIDLOCK`, this repository only) said to
  report a gridlock ruling as an ack with the facts read and gave it no
  marker, so the first two rulings under the rule were plain acks no reader
  counted; and `scripts/seat_day_census.py` read `redirect:` and `shelved:`
  anywhere in a message's text, so the briefs' and the assigns' own quotations
  of the convention counted as its use (8 of the 9 `redirect:` and 5 of the 5
  `shelved:` mentions on the refs by 2026-10-30; the four `gridlock:` mentions
  that day were all quotations). The brief now says the ack opens with
  `gridlock:` (one ruling per ack); the census reads the three markers at the
  text's opening, as `OPERATOR CALL:` is read, counts a ruling on the
  dispatcher's acks alone, keeps `START` a word anywhere (the tier-run
  announcement), and the day row names each ruling's id beside its count
  (`gridlock: 2 (<id>, <id>)`), so the rule's falsifier (a ruling the operator
  reverses) is read from the record. The protocol's Assign authority
  paragraph, its dispatcher row, Core Rule 15 and the inbox body carry the
  word, and a test holds the brief's clauses to the census's marker table.
  (`DEF-5029`)
