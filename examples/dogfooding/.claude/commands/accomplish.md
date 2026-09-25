Compatibility alias for `/implement-task --multi`.

This command is retained for existing users and muscle memory. When you invoke `/accomplish <task>`, treat it as `/implement-task --multi <task>` and execute the multi-phase branch from `/implement-task` exactly.

See `.claude/commands/implement-task.md` for the full multi-phase workflow: decompose into steps, create an execution plan with `tools/cc/execution_plan.py`, present the plan and wait for approval, execute with per-step gates, run final integration checks, and record key decisions in the cognitive blueprint.
