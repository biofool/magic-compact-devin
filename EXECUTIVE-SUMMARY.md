# Executive Summary — magic-compact-devin

## What it is

`magic-compact-devin` is a plugin for Devin CLI, Cognition's agentic coding
tool. It is not a product for somatic studios. It is developer tooling.

Its purpose: make context compaction lossless. When a long Devin session
runs out of context and gets compacted, the plugin preserves a handoff
document and the large tool outputs that compaction would otherwise drop.
After compaction, the agent gets that material back and continues working
with full context.

## Benefit to somatic studios and fields

There is no direct benefit. Studios and fields do not interact with this
software.

The benefit is indirect: maintainers of studio websites (for example
quantumaikido.com, AikiField.com, neurowellnessdojo.com) use Devin CLI for
development work. Long agent sessions on those repos stay coherent across
compactions, so fewer tasks need to be restarted or re-explained. This
reduces wasted agent time and lowers the risk of the agent losing track of
earlier decisions mid-task.

The plugin also ships quality-gate helpers (a post-edit lint hook, a
verify-change skill, an adversarial-review skill) that catch defects in
edited code earlier. That improves the reliability of agent-produced
changes on any repo where it is installed.
