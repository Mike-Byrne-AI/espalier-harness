### Fixed

- **A second session started in the same checkout no longer moves the running
  session's blueprint node into the cold store** (DEF-861). VS Code's usage
  panel starts a headless `claude` in the workspace. Its SessionStart begins
  a new blueprint node chained from the running session's node, which is
  still empty and past the prune's one-hour age guard. The prune then moved
  that node to `cc/blueprints/_cold/` while the new node named it as its
  parent. Driven on a scratch repo of 200 old nodes: a 469-byte node aged
  4200 s went cold at the second start.
  - **Now:** both prunes, `tools/cc/cognitive_blueprint.py::_prune_blueprints`
    and `espalier/cognitive_blueprint.py::_prune_blueprints`, read
    `latest.json` first. They never demote the node it names, nor the node
    that one chains from. Those two leave the eviction candidates, so the
    working set stays at `BLUEPRINT_RETENTION` and an older node goes instead.
  - A `latest.json` that is missing, unreadable, deeply nested or names no
    node prunes as before. The engine copy now catches a deeply nested file
    as the standalone copy already did.
  - **Not covered yet**, and left to the sessions-in-one-tree pack's wave C:
    - a third start in the same session still demotes the first node; a
      strict xfail row pins it;
    - the flags that SessionStart clears on every new session;
    - which node a record writes: always the node `latest.json` names.
