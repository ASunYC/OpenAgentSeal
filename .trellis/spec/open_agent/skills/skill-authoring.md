# Skill Authoring

## Required shape

Each discoverable Skill is a directory containing `SKILL.md` with YAML frontmatter:

```markdown
---
name: example-skill
description: When and why the agent should use this Skill.
---

# Instructions
```

`SkillLoader` requires `name` and `description`; it also reads optional `license`, `allowed-tools`, and `metadata`. Invalid YAML/missing required fields cause the Skill to be skipped with a warning.

## Bundle layout

Use the existing bundle conventions when needed:

- `scripts/` for executable helpers.
- `references/` for detailed material loaded on demand.
- `assets/` for reusable templates/media.
- Examples/fixtures only when they are publishable and useful to the Skill.

Keep `SKILL.md` focused on routing and execution instructions. Move large background references out of the main prompt path. Relative links/commands should resolve within the Skill directory; the loader rewrites recognized existing paths for runtime access.

## Runtime implications

- Names should be stable; duplicates may be source-qualified by the loader.
- Skill content can be exposed to the model and scripts can be executed by agents. Treat all committed content as publishable executable guidance.
- `allowed-tools` is metadata consumed by compatible runtimes, not a substitute for OpenAgentSeal's ToolRegistry/SafetyPolicy.
- A Skill present on disk can still be disabled by user configuration or its owning plugin.

## Verification

For loader-visible changes, exercise `tests/test_skill_loader.py` and `tests/test_skill_tool.py` in the parent repository when practical. For a content-only change, inspect frontmatter, relative references and scripts using the submodule's own checks; do not invent a global Skill-content validation gate that the repository does not currently have.
