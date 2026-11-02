### Fixed

- **A session in a worktree nested in the main checkout's folder no longer
  hears that it works in the main checkout.** The SessionStart note "session
  cwd is inside worktree <the main checkout> of this repository", with its
  claim that the session's plan is the main checkout's, printed on every
  such seat's banner: `_hook_utils.sibling_checkout_containing` answered the
  first sibling checkout holding the path, and the main checkout, listed
  first, holds every worktree nested in its folder. It now answers the
  deepest checkout holding the path, the session's own root among them, so a
  cwd in the root names no other checkout and a cwd in a second nested
  worktree names that worktree.
