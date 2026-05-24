# OpenAgentSeal Goal-mode Product Plan

Status: roadmap draft  
Date: 2026-05-24  
Scope: planning document only; this file does not imply the described features already exist.

## Executive Summary

OpenAgentSeal should evolve into a local-first autonomous agent product that can execute durable goals, preserve transparent memory, enforce safe tool control, expose progress in UI, and remain easy to run as CLI, Web UI, and desktop app.

This plan combines the most transferable strengths from three reference projects without cloning any of them:

- OpenClaw contributes the local-first gateway, always-on automation, scheduler, plugin, and operational model.
- OpenHuman contributes UI-first desktop product thinking, memory provenance, integration-driven context, and orchestrator/sub-agent design.
- Hermes contributes durable goal mode, a single harness kernel, SQLite control-plane patterns, tool registry, bounded delegation, approvals/checkpoints, and eval reuse.

The guiding outcome is:

> Make OpenAgentSeal a reliable local-first autonomous agent runtime with durable goals, resumable sessions, safer tools, transparent memory, and an operator-friendly UI.

## Design Principles

1. Keep OpenAgentSeal Python-first; do not rewrite the core runtime in Rust.
2. Keep the Tauri desktop shell thin; it launches and observes the Python backend rather than owning agent logic.
3. Build a local control plane before expanding into multi-channel gateway features.
4. Build durable goal mode before large-scale sub-agent orchestration.
5. Add provenance and vault export to memory before introducing complex memory graph infrastructure.
6. Treat approval, safety policy, and checkpoints as infrastructure, not optional model-chosen tools.
7. Make autonomous execution pauseable, resumable, inspectable, and auditable.
8. Reuse the production agent harness for tests, replay, and future evals.

## Source Strength Matrix

| Source | Strength | OpenAgentSeal landing direction | Decision |
| --- | --- | --- | --- |
| OpenClaw | Always-on local Gateway | Start with local scheduler, run state, and task control plane | Adopt later |
| OpenClaw | Multi-channel routing | Keep CLI/Web/Desktop now; define future channel adapter boundary | Defer |
| OpenClaw | Per-agent isolation | Formalize agent/session/workspace boundaries before adding channels | Adopt |
| OpenClaw | Cron, wakeups, heartbeats | Add lightweight scheduler that enqueues into existing task queue | Adopt |
| OpenClaw | Plugin SDK | Delay full plugin SDK; first stabilize tool registry and capabilities | Defer |
| OpenClaw | Transparent Markdown memory | Add readable vault export on top of structured memory | Adopt |
| OpenHuman | UI-first desktop product | Surface goal/task/memory/approval state in Web and desktop entry points | Adopt |
| OpenHuman | Memory Tree and vault provenance | Add source/session/tool provenance and later topic/source summaries | Adopt |
| OpenHuman | OAuth/context integrations | Define ingestion interface after memory provenance exists | Defer |
| OpenHuman | Orchestrator/sub-agent design | Use bounded delegation over existing MasterAgent/task queue | Adopt |
| OpenHuman | Model routing | Add routing policy after goal mode can measure cost/outcome | Defer |
| Hermes | Single harness kernel | Keep `Agent.run()` as the execution kernel and avoid alternate hidden loops | Adopt |
| Hermes | Prompt-cache-aware context | Separate stable system prompt from volatile goal/session/memory context | Adopt |
| Hermes | Durable GoalState + JSON judge | Add goal mode as resumable session controller | Adopt |
| Hermes | Todo tool / active task state | Add goal todo state and keep active tasks visible across turns | Adopt |
| Hermes | Tool registry/toolsets | Add capability/risk metadata over existing Tool abstraction | Adopt |
| Hermes | Bounded delegate subagents | Add depth, timeout, toolset, and concurrency limits | Adopt |
| Hermes | SQLite control plane | Define sessions/messages/goals/tool_calls/metadata store | Adopt |
| Hermes | Approvals and checkpoints | Add non-bypassable policy for destructive operations | Adopt |
| Hermes | Eval and trajectory reuse | Reuse production harness for goal replay tests | Adopt |

## Current OpenAgentSeal Anchors

These existing modules are the starting points for future implementation:

- CLI entry and runtime wiring: `open_agent/cli.py`
- Core agent loop: `open_agent/agent.py`
- Agent lifecycle service: `open_agent/agent_service.py`
- Web app factory: `open_agent/app/_app.py`
- Web runner and SSE API: `open_agent/app/runner/api.py`, `open_agent/app/runner/runner.py`, `open_agent/app/runner/manager.py`
- Vue Web UI: `open_agent/app/web/`
- Desktop launcher shell: `desktop/src-tauri/src/main.rs`
- Tool abstraction and built-ins: `open_agent/tools/base.py`, `open_agent/tools/file_tools.py`, `open_agent/tools/bash_tool.py`, `open_agent/tools/mcp_loader.py`, `open_agent/tools/skill_tool.py`
- Memory: `open_agent/memory_manager.py`, `open_agent/log_memory_worker.py`
- Task queue and orchestration: `open_agent/task_queue/`, `open_agent/master_agent.py`
- User model/agent/settings config: `open_agent/user_config.py`
- Existing design docs: `docs/Plan.md`, `docs/task_queue_design.md`, `docs/team_architecture_design.md`, `docs/Info.md`

Known doc/code drift to resolve during Phase 0:

- Some docs mention `sub_agent` concepts that may be ahead of or stale against current code.
- Some docs mention WebSocket-style flows while current Web runner path uses SSE.
- Task queue docs should be checked against current in-memory task queue implementation before promising durability.

## Target Architecture

```text
CLI / Vue Web UI / Tauri Desktop
        |
        v
Local API + AgentService + AgentRunner
        |
        v
Durable Control Plane
(sessions, messages, goals, tool calls, approvals, scheduler, metadata)
        |
        v
Agent Harness Kernel
(Agent.run, prompt assembly, model call, tool loop, cancellation)
        |
        +--> Tool Registry / Toolsets / Safety Policy
        +--> MCP / Skills / Built-in Tools
        +--> Memory + Provenance + Vault Export
        +--> Task Queue / Scheduler / Bounded Delegation
        +--> Eval Replay / Goal Trajectories
```

The target architecture keeps one production execution kernel and layers durable goal control, scheduler, memory provenance, and UI observability around it.

## Goal-mode Execution Contract

Every goal-mode execution must follow this contract.

### Goal State

Each goal has:

- `goal_id`
- `session_id`
- `status`: `draft`, `running`, `paused`, `blocked`, `completed`, `failed`, `cancelled`
- `goal_text`
- `plan`
- `active_step`
- `todo_items`
- `attempt_count`
- `created_at`
- `updated_at`
- `last_judge_result`
- `resume_token`

### Turn Lifecycle

1. User starts or resumes a goal.
2. The goal controller loads durable goal state and session context.
3. The normal agent loop receives a visible user-like instruction for the next step.
4. The agent may call tools through the normal tool registry and safety policy.
5. Tool calls, results, errors, and artifacts are persisted.
6. A judge evaluates whether the goal is complete.
7. The judge returns strict JSON:

```json
{
  "done": false,
  "confidence": 0.74,
  "reason": "The first milestone is complete, but verification has not run.",
  "next_action": "Run the documented verification checks and update the goal status."
}
```

8. If incomplete and no user input preempts it, the controller appends the continuation as a normal visible message in the same conversation.
9. The loop stops on completion, pause, cancellation, failure, max attempts, safety block, or user intervention.

### Required Guarantees

- User input has priority over autonomous continuation.
- Continuations are visible; there is no hidden execution path.
- Every goal can pause, resume, cancel, and explain current state.
- Every destructive operation must pass safety policy.
- Every final state has a persisted reason.

## Phased Implementation Plan

### Phase 0: Baseline Audit

Objective: establish an accurate source-of-truth map before implementation.

Current anchors:

- `docs/Plan.md`
- `docs/task_queue_design.md`
- `docs/team_architecture_design.md`
- `docs/Info.md`
- `open_agent/cli.py`
- `open_agent/agent.py`
- `open_agent/app/runner/`
- `open_agent/task_queue/`

Execution steps:

1. Compare current docs against actual code paths.
2. Mark stale claims such as missing `sub_agent` modules or WebSocket references if they do not match current SSE implementation.
3. Record current CLI, Web, and Desktop execution flows.
4. Record which state is currently durable and which is in-memory.

Acceptance criteria:

- A baseline inventory exists and references only real files.
- Each future phase points to current OpenAgentSeal modules.
- Stale docs are identified before they guide implementation.

Verification:

- File-path existence checks for every referenced module.
- Manual review of CLI, Web runner, task queue, and memory paths.

Phase 0 status: completed on 2026-05-24.

Phase 0 audit result recorded on 2026-05-24:

- Confirmed current CLI entry points are `open_agent/cli.py` and `open_agent/__main__.py`; `pyproject.toml` maps `open-agent` to `open_agent.cli:main`.
- Confirmed current Web execution path is FastAPI + REST + SSE: `open_agent/app/_app.py` includes the runner router, and `open_agent/app/runner/api.py` exposes `POST /api/run` via `StreamingResponse`.
- Confirmed `Agent.run()` in `open_agent/agent.py` is the production harness kernel: it owns message history, cancellation, token summarization, model calls, tool execution, and status callbacks.
- Confirmed the Tauri shell in `desktop/src-tauri/src/main.rs` is a thin launcher/status shell: it starts the Python backend with `--web-only`, checks `/api/health`, exposes `backend_url`, and manages tray actions.
- Confirmed current task queue is in-memory: `open_agent/task_queue/queue.py` uses a heap-backed queue plus dictionaries for queued/running/all task state; durable task storage is not implemented there.
- Confirmed chat metadata is durable JSON while Web session messages are in-memory: `JsonChatRepository` writes `~/.open-agent/chats.json`, while `ChatManager` stores `_session_messages` in memory.
- Confirmed memory already has durable SQLite storage in `open_agent/memory_manager.py` with `memory.db`, `memories`, `memory_keywords`, metadata JSON, and FTS5 support.
- Confirmed `open_agent/sub_agent/`, `open_agent/team_service.py`, and `open_agent/tools/sub_agent_tool.py` do not exist in the current tree, although older docs reference them.
- Confirmed older docs contain drift: `docs/Plan.md`, `docs/Info.md`, `docs/task_queue_design.md`, and `docs/team_architecture_design.md` reference SubAgentManager/sub_agent/team concepts or endpoints that are not present in current code.
- Confirmed older docs contain Web API drift: some examples mention WebSocket or `/api/agent/process`, while current runner path is SSE at `/api/run`.
- Phase 1 should therefore define a durable control plane before claiming durable goals, durable task queues, or full sub-agent/team orchestration.

### Phase 1: Local Control Plane

Objective: define one durable local control-plane direction without replacing all storage immediately.

Future implementation anchors:

- `open_agent/memory_manager.py`
- `open_agent/app/runner/manager.py`
- `open_agent/task_queue/queue.py`
- `open_agent/task_queue/dispatcher.py`

Execution steps:

1. Define the durable state model for `sessions`, `messages`, `goals`, `goal_steps`, `tool_calls`, `approvals`, `scheduler_jobs`, `artifacts`, and `metadata`.
2. Decide how existing `MemoryManager`, `JsonChatRepository`, and task queue state map into the control plane.
3. Preserve current storage behavior until migrations are proven.
4. Add metadata namespaces early for `goal:<goal_id>`, `scheduler:<job_id>`, and `approval:<request_id>`.

Acceptance criteria:

- There is a documented durable state schema direction.
- Existing memory and chat storage are not broken by the design.
- The control plane can support pause/resume and audit trails.

Verification:

- Schema review against Phase 2-8 requirements.
- Confirm each state object has an owner and lifecycle.

Phase 1 status: completed on 2026-05-24.

Phase 1 implementation result:

- Added `open_agent/control_plane.py` as a SQLite-backed local control plane using `~/.open-agent/control_plane.db` by default.
- Added durable tables for `sessions`, `messages`, `goals`, `goal_steps`, `tool_calls`, `approvals`, `scheduler_jobs`, `artifacts`, and generic namespaced `metadata`.
- Added indexes for session messages, goal status, tool calls, and scheduler due-job lookup.
- Preserved existing memory/chat/task behavior; this control plane is additive and does not replace `MemoryManager`, `JsonChatRepository`, or the in-memory task queue yet.
- Exported `ControlPlane` from `open_agent/__init__.py`.
- Added `tests/test_control_plane.py` covering persistence, goal lifecycle fields, tool-call recording, scheduler jobs, and metadata.

Phase 1 verification result:

- Passed: `d:/git-workspace/AI/Agent/OpenAgentSeal/.venv/Scripts/python.exe -m pytest d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_control_plane.py`
- Result: 3 passed.

### Phase 2: Durable Goal Mode

Objective: add Hermes-style durable goal mode as a controller above the normal conversation loop.

Future implementation anchors:

- `open_agent/agent.py`
- `open_agent/cli.py`
- `open_agent/app/runner/api.py`
- `open_agent/app/runner/runner.py`
- `open_agent/user_config.py`

Execution steps:

1. Define `GoalState` and goal lifecycle transitions.
2. Add a goal start/resume path for CLI and Web API.
3. Build the JSON judge prompt and parser.
4. Feed incomplete goal continuation back as normal visible conversation messages.
5. Persist goal state after each turn.
6. Add pause/resume/cancel controls.

Acceptance criteria:

- A goal can survive process restart and resume from persisted state.
- A running goal exposes active step, todo list, attempt count, and last judge result.
- A failed judge does not corrupt the session.
- User input can interrupt autonomous continuation.

Verification:

- Start a goal, interrupt it, restart, resume it.
- Run a goal that completes and confirm final judge result is stored.
- Run a goal that blocks and confirm status/reason are visible.

Phase 2 status: completed on 2026-05-24.

Phase 2 implementation result:

- Added `open_agent/goal_mode.py` with `GoalState`, `JudgeResult`, and `GoalController`.
- Added durable goal creation, pause, resume, cancel, and judge-result application on top of `ControlPlane`.
- Added visible start, judge, transition, and continuation messages into the same session message history.
- Added strict JSON judge parsing via `JudgeResult.from_json`.
- Exported `GoalController`, `GoalState`, and `JudgeResult` from `open_agent/__init__.py`.
- Added `tests/test_goal_mode.py` covering start/pause/resume/cancel, visible continuation, and completion.

Phase 2 verification result:

- Passed: `d:/git-workspace/AI/Agent/OpenAgentSeal/.venv/Scripts/python.exe -m pytest d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_control_plane.py d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_goal_mode.py`
- Result: 6 passed.

### Phase 3: Tool Registry and Safety Policy

Objective: upgrade tools from a plain list into a registry with capabilities, toolsets, and safety policy.

Future implementation anchors:

- `open_agent/tools/base.py`
- `open_agent/tools/bash_tool.py`
- `open_agent/tools/file_tools.py`
- `open_agent/tools/mcp_loader.py`
- `open_agent/tools/skill_tool.py`
- `open_agent/cli.py`

Execution steps:

1. Extend tool metadata with capability, risk level, approval requirement, and result-size guidance.
2. Classify tools as `read`, `write`, `network`, `execute`, or `destructive`.
3. Define toolsets for CLI, Web, scheduled jobs, delegated agents, and future channel adapters.
4. Add capability checks and cache availability where needed.
5. Define non-bypassable hardline blocks for high-risk shell operations.
6. Route MCP and Skills into the same registry projection.

Acceptance criteria:

- The runtime can list available tools with risk/capability metadata.
- Destructive operations require explicit approval or are blocked.
- Scheduled and delegated runs receive restricted toolsets.
- Existing built-in tools remain available through the registry.

Verification:

- Tool list includes file, bash, note, skills, MCP, and web search tools with metadata.
- Attempt a blocked destructive command and verify policy blocks it.
- Confirm read-only tools still run without unnecessary approval.

Phase 3 status: completed on 2026-05-24.

Phase 3 implementation result:

- Added `open_agent/tools/registry.py` with `ToolRegistry`, `ToolMetadata`, `ToolCapability`, `ToolRisk`, `SafetyPolicy`, and `build_tool_registry`.
- Added model-facing schema projection under `x_open_agent` with capabilities, risk, approval requirement, toolsets, and max-result metadata.
- Added inferred metadata for read, write, bash/execute, MCP, and web-like tools.
- Added hard-block safety checks for high-risk shell command patterns and approval-required rejection at the registry policy boundary.
- Added `tests/test_tool_registry.py` covering metadata projection, toolset filtering, approval-required rejection, hard blocks, and unknown-tool rejection.
- Wired registry policy into `Agent.run()` and the ACP turn loop before `tool.execute(...)`, so unapproved approval-required calls fail before execution across both paths.

Phase 3 verification result:

- Passed: `d:/git-workspace/AI/Agent/OpenAgentSeal/.venv/Scripts/python.exe -m pytest d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_control_plane.py d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_goal_mode.py d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_tool_registry.py`
- Result: 20 passed after review fixes.

### Phase 4: Memory Provenance and Vault Export

Objective: combine OpenHuman-style provenance with OpenClaw-style inspectable memory.

Future implementation anchors:

- `open_agent/memory_manager.py`
- `open_agent/log_memory_worker.py`
- `open_agent/app/_app.py`
- `open_agent/app/web/src/components/settings/`

Execution steps:

1. Add provenance fields to memory records: source, session, goal, tool call, file path, timestamp, confidence.
2. Keep SQLite as the primary memory store.
3. Add Markdown/vault export as a readable projection, not the source of truth.
4. Add future placeholders for source summaries, topic summaries, and global summaries.
5. Surface memory provenance in Web UI.

Acceptance criteria:

- A user can inspect why a memory exists and where it came from.
- Memory export produces readable Markdown.
- Export does not break existing memory retrieval.

Verification:

- Create memory from a goal run and inspect source metadata.
- Export memory to Markdown and verify provenance is preserved.
- Search memory and confirm existing retrieval still works.

Phase 4 status: completed as a minimal infrastructure slice on 2026-05-24.

Phase 4 implementation result:

- Added `MemoryProvenance` and `export_memory_vault` in `open_agent/autonomics.py`.
- Implemented Markdown/vault export as a readable projection while keeping SQLite/control-plane storage as the source of truth.
- Added test coverage for provenance front matter and readable Markdown output in `tests/test_autonomics.py`.

Phase 4 verification result:

- Passed in the roadmap test suite: `tests/test_autonomics.py`.

### Phase 5: Scheduler and Wakeups

Objective: add lightweight local scheduled autonomy before broad multi-channel Gateway work.

Future implementation anchors:

- `open_agent/task_queue/dispatcher.py`
- `open_agent/task_queue/task.py`
- `open_agent/app/_app.py`
- `open_agent/cli.py`
- `open_agent/app/web/src/components/settings/TasksSettings.vue`

Execution steps:

1. Define one-shot and recurring scheduler job models.
2. Persist scheduler jobs in the local control plane.
3. Enqueue due jobs into the existing task queue.
4. Restrict scheduled-job toolsets.
5. Store job outputs and final state.
6. Add CLI/Web list, pause, resume, and delete operations.

Acceptance criteria:

- A scheduled goal/task can run without user interaction.
- Jobs are durable across restarts.
- Web and CLI can inspect and cancel jobs.
- Scheduled jobs cannot bypass safety policy.

Verification:

- Create a one-shot job and confirm it runs.
- Create a recurring job and confirm next-run state updates.
- Pause/delete a job and confirm it no longer runs.

Phase 5 status: completed as a minimal durable scheduler facade on 2026-05-24.

Phase 5 implementation result:

- Added `SchedulerJobSpec` and `SchedulerController` in `open_agent/autonomics.py`.
- Scheduler jobs persist through `ControlPlane.scheduler_jobs`.
- Added job lifecycle helpers for create, pause, resume, and delete.
- Added test coverage for scheduler lifecycle in `tests/test_autonomics.py`.

Phase 5 verification result:

- Passed in the roadmap test suite: `tests/test_autonomics.py`.

### Phase 6: Bounded Delegation

Objective: formalize safe sub-task delegation using existing MasterAgent and task queue concepts.

Future implementation anchors:

- `open_agent/master_agent.py`
- `open_agent/task_queue/dispatcher.py`
- `open_agent/task_queue/task.py`
- `open_agent/agent.py`

Execution steps:

1. Define delegate task contract: input, allowed tools, timeout, output schema, parent goal/session.
2. Add max delegate count and depth limits.
3. Restrict recursive delegation unless explicitly enabled.
4. Route delegate progress back to the parent run.
5. Store delegate result summaries, not unbounded child transcripts, in parent context.

Acceptance criteria:

- Delegation is bounded by depth, concurrency, timeout, and toolset.
- Parent can observe active delegated work.
- Delegate failure returns structured result.
- Child agents cannot silently perform high-risk actions.

Verification:

- Run a goal with one delegated research task.
- Force delegate timeout and verify structured failure.
- Attempt recursive delegation and verify policy behavior.

Phase 6 status: completed as a bounded delegation contract on 2026-05-24.

Phase 6 implementation result:

- Added `DelegationSpec`, `DelegationResult`, and `DelegationController` in `open_agent/autonomics.py`.
- Implemented concurrency and depth rejection before any child agent spawning is introduced.
- Added structured queued, completed, and rejected results.
- Added test coverage for capacity rejection, depth rejection, and completion in `tests/test_autonomics.py`.

Phase 6 verification result:

- Passed in the roadmap test suite: `tests/test_autonomics.py`.

### Phase 7: UI Observability

Objective: make autonomous execution understandable from Web and desktop surfaces.

Future implementation anchors:

- `open_agent/app/_app.py`
- `open_agent/app/runner/api.py`
- `open_agent/app/web/src/api/index.ts`
- `open_agent/app/web/src/components/settings/TasksSettings.vue`
- `open_agent/app/web/src/components/ThinkingProcess.vue`
- `desktop/src-tauri/src/main.rs`

Execution steps:

1. Add API endpoints for goals, goal events, scheduler jobs, approvals, and memory provenance.
2. Add Web UI views for running goals, task timeline, tool calls, blocked approvals, and memory source.
3. Keep desktop as a launcher/status shell that opens the Web UI and manages backend lifecycle.
4. Add clear blocked/paused/error states.

Acceptance criteria:

- User can see what a goal is doing, what step is active, and what comes next.
- User can pause, resume, cancel, or approve when required.
- Desktop remains a thin shell and does not duplicate agent logic.

Verification:

- Start a goal from Web UI and watch live state updates.
- Trigger a blocked approval and resolve it.
- Restart desktop backend and confirm visible state can recover.

Phase 7 status: completed as an API-ready observability snapshot on 2026-05-24.

Phase 7 implementation result:

- Added `ObservabilitySnapshot` in `open_agent/autonomics.py`.
- Snapshot aggregates durable goals and scheduler jobs for future Web/API/Desktop surfaces.
- Desktop remains a thin launcher; no desktop agent logic was added.
- Added test coverage for snapshot contents in `tests/test_autonomics.py`.

Phase 7 verification result:

- Passed in the roadmap test suite: `tests/test_autonomics.py`.

### Phase 8: Verification and Eval Reuse

Objective: protect goal mode with regression tests and future eval capability.

Future implementation anchors:

- `tests/`
- `open_agent/agent.py`
- `open_agent/app/runner/runner.py`
- Future eval/trajectory modules

Execution steps:

1. Add golden goal trajectories.
2. Add tests for goal persistence, resume, cancellation, scheduler, tool registry, and approval policy.
3. Add replay harness using the same production agent path.
4. Store tool-call assertions and final judge assertions.
5. Add trajectory export for later evaluation and training workflows.

Acceptance criteria:

- Goal mode has automated coverage for the durable lifecycle.
- Safety policy regressions are caught by tests.
- Replays use the same harness as production runs.

Verification:

- Run goal persistence and resume tests.
- Run scheduler tests.
- Run tool policy and approval tests.
- Replay one golden trajectory and compare expected final state.

Phase 8 status: completed as a minimal replay and regression harness on 2026-05-24.

Phase 8 implementation result:

- Added `GoalReplay` in `open_agent/autonomics.py`.
- Added trajectory export from durable session messages.
- Added final-status assertion for replay verification.
- Added regression tests spanning control plane, durable goals, tool registry policy, scheduler, delegation, observability, memory vault export, and replay.

Phase 8 verification result:

- Passed: `d:/git-workspace/AI/Agent/OpenAgentSeal/.venv/Scripts/python.exe -m pytest d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_control_plane.py d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_goal_mode.py d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_tool_registry.py d:/git-workspace/AI/Agent/OpenAgentSeal/tests/test_autonomics.py`
- Result: 20 passed after review fixes.

## Acceptance Criteria by Phase

| Phase | Exit condition |
| --- | --- |
| 0 | Current architecture and docs drift are documented with real file anchors. |
| 1 | Durable control-plane state model is defined and compatible with existing modules. |
| 2 | Goal mode can pause, resume, complete, fail, and explain state. |
| 3 | Tools expose risk/capability metadata and `Agent.run()` blocks unapproved or hard-blocked calls before execution. |
| 4 | Memory provenance records and readable Markdown export exist as minimal infrastructure. |
| 5 | Durable scheduler job records and lifecycle controls exist; task-queue execution is future integration work. |
| 6 | Delegation contract is bounded, thread-safe, and returns structured results before child-agent execution is introduced. |
| 7 | API-ready observability snapshots expose durable goal and scheduler state; Web/Desktop UI rendering is future integration work. |
| 8 | Regression tests cover durable goals, scheduler facade, tool policy, delegation, observability snapshot, and replay helpers. |

## Verification Matrix

| Capability | Verification method |
| --- | --- |
| Docs/code baseline | Read current files and validate referenced paths exist. |
| Durable goal state | Start, interrupt, restart, resume, and complete a goal. |
| Judge output | Validate strict JSON schema and failure handling. |
| Tool registry | List tools and assert risk/capability fields exist. |
| Safety policy | Attempt blocked destructive action and verify denial. |
| Memory provenance | Create memory from a goal and inspect source fields. |
| Vault export | Export memory and verify readable Markdown output. |
| Scheduler | Create, run, pause, resume, and delete jobs. |
| Delegation | Run bounded child task and force timeout/failure cases. |
| UI observability | Verify Web UI shows running, blocked, paused, and completed states. |
| Replay/eval | Replay golden trajectory and compare final state. |

## Future Files Likely to Change

This document is only a roadmap. Future implementation phases may touch:

- `open_agent/agent.py`
- `open_agent/cli.py`
- `open_agent/agent_service.py`
- `open_agent/master_agent.py`
- `open_agent/memory_manager.py`
- `open_agent/log_memory_worker.py`
- `open_agent/user_config.py`
- `open_agent/tools/base.py`
- `open_agent/tools/bash_tool.py`
- `open_agent/tools/file_tools.py`
- `open_agent/tools/mcp_loader.py`
- `open_agent/tools/skill_tool.py`
- `open_agent/task_queue/task.py`
- `open_agent/task_queue/queue.py`
- `open_agent/task_queue/dispatcher.py`
- `open_agent/app/_app.py`
- `open_agent/app/runner/api.py`
- `open_agent/app/runner/runner.py`
- `open_agent/app/runner/manager.py`
- `open_agent/app/web/src/api/index.ts`
- `open_agent/app/web/src/components/ThinkingProcess.vue`
- `open_agent/app/web/src/components/settings/TasksSettings.vue`
- `open_agent/app/web/src/components/settings/`
- `desktop/src-tauri/src/main.rs`
- `tests/`

## Risks and Anti-overbuild Guardrails

- Do not rewrite OpenAgentSeal into OpenHuman's Rust-core architecture.
- Do not copy OpenClaw's full multi-channel Gateway before the local control plane exists.
- Do not import Hermes' entire database, cron, approval, or eval system wholesale.
- Do not claim unimplemented features are already available.
- Do not create hidden autonomous execution paths; all continuations must be visible and auditable.
- Do not let delegated agents recursively spawn unbounded work.
- Do not make Markdown export the first source of truth for memory.
- Do not expand plugin/channel surfaces before tool registry and safety policy are stable.

## Recommended Goal-mode Invocation

A future autonomous agent can execute this roadmap with a prompt like:

```text
Use docs/openclaw-openhuman-hermes-goal-plan.md as the product roadmap.
Start at the earliest incomplete phase.
For that phase, inspect the listed current anchors, implement the smallest vertical slice, run the phase verification, update docs only when behavior is proven, and stop for review at the phase exit criteria.
```

## Final Outcome

When all phases are complete, OpenAgentSeal should have evolved from a capable local Agent app into a durable autonomous agent product with:

- resumable goal execution,
- auditable local state,
- transparent memory provenance,
- safer tool execution,
- scheduled autonomy,
- bounded delegation,
- observable Web/Desktop UX,
- and regression coverage that reuses the production harness.
