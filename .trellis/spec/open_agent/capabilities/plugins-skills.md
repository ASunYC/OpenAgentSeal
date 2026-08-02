# Plugins and Skills

## Ownership distinction

- Built-in Skill content is checked out in the `open_agent/skills` Git submodule.
- `SkillLoader` discovers `SKILL.md` files from built-in and plugin-provided roots.
- `ListSkillsTool` and `GetSkillTool` implement progressive disclosure to the model.
- `PluginManager` owns marketplace registration, installation state, enabled state, settings and effective Skill/MCP projection.
- Bundled plugins under `open_agent/plugins/bundled/` use the same manifest/settings concepts while shipping with the application.

## Marketplace and install flow

```text
marketplace source
  -> marketplace manifest + plugin source resolution
  -> install into application data plugin root
  -> read plugin manifest / settings schema / MCP config / Skills
  -> enabled runtime view
  -> Skill roots + effective MCP servers
```

Plugin identity is `<plugin>@<marketplace>`. Paths and names are validated as safe segments and resolved relative to the declared roots.

## Skill contract

`SkillLoader` requires `SKILL.md` YAML frontmatter with `name` and `description`. It reads optional license, allowed-tools and metadata, rewrites existing relative Skill asset/reference paths for runtime access, and skips invalid Skills with a warning. Duplicate names are qualified by source/plugin context.

Do not edit the Skill submodule while implementing an application loader/UI change unless the content change is explicitly in scope. Conversely, Skill-only changes should not modify the runtime loader without a demonstrated compatibility need.

## Settings and secrets

Plugin `.open-agent/settings.json` describes publishable field metadata (`text`, `url`, `secret`, `model`, `select`, `boolean`). Saved values live in application data. Secret detail values are masked; saving the mask preserves the existing secret. Effective MCP expansion may use the real stored secret but must not return it through list/detail APIs.

## Enabled state

- Disabled plugin: no runtime Skills or MCP servers.
- Enabled plugin with disabled MCP server: Skills may remain, but that server is absent from normal runtime aggregation.
- Settings UI may request disabled server metadata for management.
- Marketplace removal does not implicitly uninstall installed plugin files unless the manager contract explicitly changes.

## Verification

Use `tests/test_plugins.py`, `test_skill_loader.py`, `test_skill_tool.py`, `test_mcp.py`, `test_mcp_api.py`, `test_mineru_plugin.py`, and packaging entry-point tests. Cover projection as well as persistence/list output.
