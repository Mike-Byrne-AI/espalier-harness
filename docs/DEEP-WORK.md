# Deep Work Protocol: Engineering Emergent Quality in Claude Code Sessions

## The Design Bet

When Claude hits a tool-use limit mid-session and the user presses Continue,
the continuation work *often appears* higher quality than what preceded it.
It tends to surface:

- Structural gaps that were invisible during generation
- Cross-file patterns that connect separately-built artifacts
- Architectural refinements that weren't in the original plan
- Early work revised with insights from later work

> **Status: hypothesis, not measurement.** This is a pattern noticed
> informally during our own use — not a controlled result: no pre-registered
> metric, no n, no spread, no control arm. Treat it as the design bet this
> protocol is built on, not a proven effect. (Per this repo's own epistemic
> rules: direction ≠ magnitude; distrust self-report.)

As anecdotes from this project's own history, continuation passes are where
the settings-profile system and several structural-coherence fixes took
shape. That is one project's experience, not a sample.

## The Mechanism

**Production mode** (sequential generation):
```
Generate File 1 → Generate File 2 → ... → Generate File N
     ↑                                         ↑
  Full attention                          Full attention
  on File 1                               on File N
                                          Weak attention on Files 1-3
```

Attention is locally focused. You're thinking about what you're currently
building. Earlier files are in context but receive decreasing attention weight.

**Review mode** (after output becomes input):
```
[File 1] [File 2] [File 3] ... [File N]  ← all processed as input
    ↕        ↕        ↕            ↕
         Equal parallel attention
         Cross-file patterns visible
```

All artifacts are processed with equal weight. Patterns that span multiple
files — which is where architectural insights live — become accessible.

**The phase transition**: Output → Input. Content you generated gets
re-processed as content you're reading. The attention geometry changes
from sequential/local to parallel/global. This is the mechanism.

## Engineering the Effect

### Method 1: /reflect Command (Single Pass)

After completing a generation burst, run `/reflect`. This forces a deliberate
re-read of all produced artifacts and a structured search for gaps, patterns,
and opportunities.

**When:** After every 3-5 files generated, or every 30 minutes, or whenever
you finish a logical unit of work.

**Effect:** Catches ~70% of what a tool-use limit continuation would catch.
Good for routine quality improvement.

### Method 2: Accumulate → Produce → Reflect Cycle (Multi-Pass)

The full engineered version of the tool-use limit effect:

```
Phase 1: ACCUMULATE (maximize input context before generating)
  ↓
Phase 2: PRODUCE (generate artifacts from rich context)
  ↓
Phase 3: REFLECT (re-read everything, find gaps and opportunities)
  ↓
Phase 4: REFINE (fix gaps, act on opportunities)
  ↓
Phase 5: REFLECT AGAIN (second-order improvements)
  ↓
(repeat Phases 4-5 until diminishing returns)
```

#### Phase 1: ACCUMULATE

Before generating anything, spend tool calls on READING:

```
Read the project's existing code
Read reference implementations
Read the user's stated requirements
Read any relevant standards or specs
Read prior session artifacts (blueprints, ESPALIER_MEMORY.md)
```

The goal is to build the richest possible internal model before producing
a single file. This is the "spend the most time accumulating context"
approach — every tool call in this phase is a read, not a write.

In practice, tell Claude Code:
```
"Before you write anything, I want you to deeply read [these files/this
codebase/these references]. Understand the patterns, the architecture,
the conventions. Build your mental model. Then tell me what you've
observed before we start building."
```

The observation report at the end of Phase 1 serves two purposes:
1. It forces Claude Code to articulate its understanding (which deepens it)
2. It gives the user a chance to correct misunderstandings before generation

#### Phase 2: PRODUCE

Now generate, but with a key discipline: **generate in dependency order,
and pause between logical groups.**

Bad: Generate all 15 files in one burst.
Good: Generate the core 3 files → pause → generate the next 4 → pause → etc.

Each pause is a mini-reflect: "Do the files I just wrote work together?
Does anything I planned to write next need to change based on what I
just learned while writing?"

#### Phase 3: REFLECT

Run `/reflect`. This is the engineered tool-use limit. Re-read everything.
Look for structural gaps, emergent patterns, missing connections, quality
gradient.

#### Phase 4-5: REFINE + RE-REFLECT

Act on findings. Then reflect again. The second reflection is where the
highest-value innovations typically appear, because it operates on a
context that includes both the original artifacts AND the improvements
from the first reflection.

### Method 3: Deliberate Context Boundaries (Session Architecture)

For large projects, architect the session itself as multiple passes:

```
Session structure:
  Turn 1: "Read [all reference material]. Tell me what you observe."
  Turn 2: "Now design the architecture based on your observations."
  Turn 3: "Generate the core files."
  Turn 4: "Read back everything you generated. What's missing?"
  Turn 5: "Generate the remaining files incorporating your findings."
  Turn 6: "Final review. What emerged that we didn't plan?"
```

Each turn is a deliberate context boundary. The user's message between
turns forces the output→input transition. Claude Code re-reads its own previous
output on every turn.

This is the manual version of what tool-use limits do accidentally.
The advantage: you control WHERE the boundaries fall (at logical
breakpoints, not arbitrary token counts).

### Method 4: Agent-as-Reviewer Pattern

Spawn a review agent after generation:

```
"Use the code-reviewer agent to review everything I just built."
```

The agent spawns in its own context window and reads the generated
files as fresh input. It has no memory of the generation process — it
sees only the artifacts. This is a more radical version of the
output→input transition: a completely separate context evaluating the
work.

The downside: the agent lacks the reasoning context that produced the
artifacts. It can find structural issues but not emergent opportunities
(those require understanding WHY things were built the way they were).

Best used in combination with /reflect, not as a replacement.

## The Prompt Pattern

The most direct way to trigger the effect in any Claude Code session:

```
"Stop. Before you continue:

1. Re-read every file you've created this session.
2. Hold all of them in mind simultaneously.
3. What patterns emerge across files that aren't in any single file?
4. What's missing that would connect what exists?
5. What could exist that we didn't plan but is now obvious?

Report your findings, then we'll decide what to act on."
```

This prompt:
- Forces the mode transition (stop producing, start reviewing)
- Requires actual re-reading (not reasoning from memory)
- Asks specifically for cross-artifact patterns (the highest-value finds)
- Separates discovery from action (report before fixing)

## Measuring the Effect

To validate that the reflection is working, track:

1. **Gap count per pass:** How many structural gaps does each /reflect find?
   Should decrease with each pass (convergence).

2. **Innovation count per pass:** How many emergent opportunities surface?
   Often increases from pass 1 to pass 2, then decreases (the sweet spot
   is pass 2-3).

3. **Cross-reference density:** After reflection, how many more cross-file
   references exist? Higher density = better integration.

4. **Quality gradient:** Are early files getting refreshed? If /reflect
   doesn't trigger any updates to early files, it's not looking hard enough.

## Integration with Blueprint System

The blueprint system captures reasoning state for CROSS-SESSION continuity.
/reflect captures reasoning state for WITHIN-SESSION quality improvement.
They're complementary:

- /reflect after each generation pass → within-session emergent quality
- /handoff captures and finalizes the cognitive blueprint → cross-session reasoning continuity
- /context-load at session start → re-activates cross-session context

The full stack:
```
Session N:
  /context-load (activate prior session's blueprint)
  → accumulate → produce → /reflect → refine → /reflect
  → /handoff (captures reasoning, finalizes cognitive blueprint)

Session N+1:
  /context-load (inherits Session N's accumulated context)
  → starts from a higher baseline than Session N started from
  → accumulate → produce → /reflect → ...
```

Each session both benefits from AND contributes to the accumulated
context chain. The blueprint is the serialization format. /reflect
is the within-session quality mechanism. Together they are designed to
compound context across the project's lifetime — the intended effect
this protocol bets on, not a measured outcome.
