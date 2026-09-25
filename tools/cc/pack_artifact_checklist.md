Pack-artifact review — fixed checklist (TP-62 v2)

For each of the following, report BLOCK / WARN / NIT / PASS:

1. Line-number accuracy. Every `file.py:N` reference resolves to a
   line that exists in the named file. Surrounding context matches
   what the pack claims.
2. Symbol-name accuracy. Every function / class / constant cited
   exists at the named path. Spot-check a representative sample of
   cited symbols.
3. Cross-pack dependency. If the pack modifies files also modified
   by another in-flight pack, the dependency is spelled out in a
   "Cross-pack coordination" section.
4. Test-naming consistency. Test classes follow the `TestX` pattern;
   test functions follow `test_{specific_behavior}` per the project's
   CONVENTIONS.md.
5. Bypass-class numbering. If the pack adds `BC-NNN` corpus rows,
   the numbers are contiguous with the current corpus state, OR
   explicit non-contiguous numbering is documented.
6. Conflicting prescriptions. The pack does not prescribe a change
   that another in-flight pack reverses.
7. Effort calibration. Per-sub-task estimates are not wildly off
   for the scope listed. Total matches sum of parts.
8. Pass-criteria realism. Each pass criterion is either testable
   OR documented as a manual smoke. None are mutually inconsistent.
9. Surface additions and removals declared. For every path in the
   pack's `### Added-paths` and `### Removed-paths`, the pack's
   `## Implementation` also updates the applicable count constants,
   name-sets, `.claude`/vendor/asset mirrors,
   `PACK_MANIFEST`/`LIVE_SURFACE`/`COMMANDS` regens, and the integrity
   manifest — in reverse for a removal, plus a sweep of inbound
   references — cross-check against `espalier surface-impact` (0-D)
   output. A file can pass items 1–8 and 0-B cleanly yet trip a
   count-pin, mirror-parity, hygiene, or provenance contract only the
   full suite catches.

Output format per item: SEVERITY • PACK_LINE • CLAIM • REALITY •
SUGGESTED_FIX.

Severity must be one of: BLOCK, WARN, NIT, PASS.
