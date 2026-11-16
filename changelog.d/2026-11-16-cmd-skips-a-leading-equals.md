### Fixed

- **The guard reads a cmd statement's program word past a leading `=`, as
  cmd runs it.** cmd skips a `=` before a statement's program word, as it
  skips `,` and `;`: after a separator, at the line's start, after an `if`
  condition and after `call` (driven on Windows 11, cmd 10.0.26200). The
  guard's cmd reader read the `=` as part of the word, so a dotenv read cmd
  ran behind one (`cmd /c "echo a &=type .env"`, `cmd //c '=type .env'`)
  was allowed on both tools while its `,` twin was refused, a recursive
  delete there met no wall, and a harness variable set by `=set`, or a
  `claude` launched as `=claude` or `@claude`, got past the check that
  refuses a launch after the set. Every reader of a statement's program
  word now skips the `=` (the prefix walk, the delete reader, both secret
  legs and the harness-variable check). Every refusal the reader made
  before stands, and a call that holds no cmd pays nothing new.
