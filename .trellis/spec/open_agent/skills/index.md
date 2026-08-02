# Built-in Skill Content

`open_agent/skills` is a Git submodule and a separately declared Trellis package. It contains model-visible/executable Skill bundles, not the OpenAgentSeal backend or frontend.

Read [Skill Authoring](./skill-authoring.md) for content changes. Runtime loading, plugin-provided roots, progressive disclosure and name qualification are documented in [Plugins and Skills](../capabilities/plugins-skills.md).

The `backend/` and `frontend/` directories beside this file were produced by the initial Trellis package misdetection. Their documents describe main-application language conventions and are retained for compatibility with the bootstrap task; they are not conventions for organizing Skill bundles.

Because this directory is a submodule:

- Check its own Git status and branch before editing.
- A parent-repository change records only the submodule commit pointer.
- Do not mix a Skill-content release with unrelated loader/application changes unless the task requires both.
- Never copy credentials, personal absolute paths or environment-specific endpoints into Skill instructions, examples, fixtures, scripts or references.
