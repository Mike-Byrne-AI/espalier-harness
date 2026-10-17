### Fixed

- **A test fixture's git repository no longer repacks itself while a test
  copies it.** The census in `tests/test_cli_deploy.py` copies one shared
  tree for each command it runs. In CI that copy failed four times with
  whole object folders gone from the source mid-copy. The writer is git's
  own: each fixture commit spawns `git maintenance run --auto` in the
  background (seen by GIT_TRACE on the census build). DEF-1168 shut that
  writer off in `initialized_repo_root`, and this is the same fix at its
  sister sites.
  - **The keys:** `gc.auto 0`, `gc.autoDetach false` and
    `maintenance.auto false`, set right after `git init`. They now live in
    `tests/_quiet_git.py`.
  - **The sweep:** 13 committed trees that a test copies or several tests
    share, of which only `initialized_repo_root` set the keys. The other 12
    now set them too:
    - the census tree's builder;
    - the adopter-tree builder, whose trees back seven of the 13;
    - the four fuse hosts, since fuse copies a host's `.git` right after
      its commit.

    So do two more repositories that a test clones right after committing
    to them. `initialized_repo_root` now reads its keys from the same
    tuple. Every site has a pin that reads the keys back. The census
    tree's pin traces a commit for the spawn.
  - **Left as they are:**
    - about 185 function-scoped repositories that no other test reads and
      nothing copies;
    - four bare origins that a push writes and a test then clones. Their
      writer would be the push's own `gc --auto` over a few objects, not a
      commit's maintenance.
  - **The census test's copy, if it still fails,** now reports what moved
    its source: the object store at build and now, git's gc and lock files,
    git's version, and on Linux every process whose working directory,
    open files or command line name the tree.
