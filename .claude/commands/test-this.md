Generate tests for a specific file matching project patterns. Delegates to the test-writer agent for orthogonal-context generation.

The user will specify a file path.

1. Identify the target file and confirm it exists. If the user did not name
   a file, ask which one.

2. Dispatch the **test-writer** subagent (`subagent_type='test-writer'`). Brief it on:
   - The target file path.
   - The project's fixture conventions (tmp_path, subprocess stdin mocking).
   - Test file naming (`tests/test_{module}.py`) and function naming
     (`test_{specific_behavior}`).
   - Whether the target needs unit, integration, or contract coverage —
     ask the user if unclear; the marker selection affects which
     `pytest -m "..."` slice picks up the new test.

   The agent runs in its own context and emits a test file matching the
   project style exactly. Its output is the test content; this command
   writes it to disk.

3. Write the test file at the path the agent suggested.

4. Run the new tests:
   ```bash
   pytest -q tests/test_{module}.py
   ```

5. Report results. If any test fails, decide with the user whether to
   fix the production code or refine the test — the agent's output is a
   draft, not a guarantee.
