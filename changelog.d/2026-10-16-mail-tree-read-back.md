### Fixed

- **A mail send from Windows no longer pushes an empty tree.** Since the
  Session Log transport landed, the mail channel built each commit by feeding
  git its file list on standard input. On Windows that input passes through a
  text-mode pipe, which rewrites each line ending, so git read a file name
  ending in a carriage return; on the Windows host that reported it the tree
  came out empty, and the send pushed it: every message the seat had sent
  vanished from origin's tip of its mail ref. The file list now goes to git as
  arguments, and the shared runner refuses lines of text on standard input.
  The tree git writes is read back before the commit, and a tree that differs
  in any file from what it was given is refused before any ref moves or
  anything is pushed; the push itself refuses a commit with an empty tree,
  whatever built it. This covers a send, a release, a claim and a Session Log
  park, and a refusal says not to retry.
