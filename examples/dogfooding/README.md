# Espalier-Harness Dogfooding

The files in this directory describe how Espalier-Harness uses agents,
commands, and skills on **its own repo**. They are NOT deployment
templates for user repos.

The contents reference Espalier-Harness's specific architecture:

- The `tools/cc/` <-> `espalier/` layer model
- The TP-N task pack format
- Espalier-specific hook contract details
- The cognitive blueprint and reflect_protocol systems

A user repo running `espalier init` does **not** receive these
files. They live here for:

1. **Transparency.** Espalier-Harness self-hosts. Showing how we use
   our own tool on our own repo is part of the credibility story.
2. **Reference.** If you want to write your own agents/commands/skills
   for your repo, these are real examples to start from. Copy and
   adapt -- don't deploy verbatim.
3. **Templating source.** When language-aware templates land (planned
   for a future release), these are the design source for what gets
   templated.

## What does deploy by default

See the main README. Briefly: hooks (`tools/cc/hooks/`),
`.claude/settings.json`, `CLAUDE.md`, `ESPALIER_MEMORY.md`, integrity manifest,
the `tools/cc/statusline.py` prompt segment, plus the full dogfooded
roster shipped here — 7 agents, 17 commands, 9 skills. Every packaged
agent, command, and skill deploys to every repo (the harness-dev
deploy tier was retired). (Treat all of them as starting examples to
customize, not finished templates.)

The deployment is honest about this: the bundled `code-reviewer.md`,
`docs-maintainer.md`, etc. read as Python-flavored because they were
authored to review Espalier-Harness's own Python code. Downstream
consumers should expect to rewrite the body of each agent / command to
match their repo's language and team conventions. A language-aware
templating layer that renders generic versions automatically is planned
for a future release — see the main README's "Honest scope" section.

## Contract-infrastructure worked example

[`contracts/`](contracts/) shows the smallest viable shape for a
`StringContract` consumer using the shared
[`tests/_contracts.py`](../../tests/_contracts.py) primitives + the
`# contract: ok <rule-id> <reason>` opt-out grammar. An
adopter authors their own consumer when they have a canonical fact
(event name, schema version, denial reason) repeated across N sources
that must stay in sync. Copy the shape, register a `rule_id` row in
your own ceiling registry, write the parametrized test.

## Roadmap

A future release will introduce a templating layer that renders generic
versions of these files based on detected language, test framework, and
convention paths. Until then, treat this directory as reference, not
template.
