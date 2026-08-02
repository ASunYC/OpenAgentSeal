# API and Configuration Shapes

## Endpoint families

The API has evolved incrementally and does not expose one envelope:

- Chat/history/runtime endpoints often return direct domain dictionaries/lists.
- Workspace operations often return `{ ok, ... }`.
- Settings, plugins, skills and tasks often return `{ success, ... }`.
- `/api/run` and mobile run operations stream SSE events.
- Sandbox terminal I/O uses WebSocket frames.

Match the family and the exact TypeScript return type. Do not add a generic response wrapper to one endpoint while leaving its consumer unchanged.

## Configuration contracts

- Pydantic models in `config.py` and `user_config.py` define runtime/model/settings structures.
- `api/index.ts` exports many feature-specific interfaces for settings, model/provider diagnostics, plugin manifests/settings, mobile and sandbox.
- Settings forms may send partial updates; backend persistence owns defaults and masking.
- Environment/config precedence is behavior, not merely a type shape.

## Cross-layer checklist

When adding or changing a field:

- Python request/response/Pydantic model.
- Route serialization and error behavior.
- Persisted default/legacy read behavior.
- TypeScript interface and API method.
- Store/component form and display.
- Mobile/desktop variant if the field affects runtime connection or capabilities.
- Focused Python and frontend model/build verification.

Avoid `as unknown as` as a permanent substitute for defining an actual shared response. Some current dynamic task/plugin paths use broad records; improve only within the task's boundary and retain backward compatibility.
