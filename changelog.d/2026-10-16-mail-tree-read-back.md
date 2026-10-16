### Fixed

- **A mail send from Windows no longer pushes an empty tree.** Since the
  Session Log transport landed, the mail channel built each commit by feeding
  git its file list on standard input. On Windows that input passes through a
  text-mode pipe, which rewrites each line ending, so git read a file name
  ending in a carriage return and wrote an empty tree, and the send pushed it:
  every message the seat had sent vanished from origin's tip of its mail ref.
  The file list now goes to git as arguments. The tree git writes is read back
  before the commit, so a tree that is missing a file it was given is refused
  before any ref moves or anything is pushed. This covers a send, a release, a
  claim and a Session Log park.
