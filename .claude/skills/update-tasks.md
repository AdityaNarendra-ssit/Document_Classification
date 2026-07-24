# update-tasks

## Description

Update `Tasks.md` after a feature is developed or a task is completed. The skill reads the current task table, determines which work was just finished or newly identified, and rewrites the file while preserving its existing structure.

## When to use

Invoke this skill immediately after:

- A tracked task is completed.
- A new task is discovered during implementation.
- A task is reassigned or reprioritized.
- A batch of related tasks is finished.

## How to run

Use `/update-tasks` and provide a concise natural-language summary of what changed, for example:

```
/update-tasks Completed docstring and loguru logging across the codebase. Added loguru dependency. Created PROJECT_STATUS.md. Assigned Claude to both.
```

The skill will:

1. Read `Tasks.md`.
2. Mark any explicitly completed tasks as done (status `Done`).
3. Add any newly mentioned tasks to the bottom of the table with the next available serial number, default category `TBD`, and default assignee `TBD`.
4. Update the `Last updated:` line to today's date.
5. Rewrite `Tasks.md` in the same table format.

## Table format

`Tasks.md` must keep this exact header and column layout:

```markdown
# 1. This file is for tracking the To-do, improvements and features we need to add, and who is assigned to it.

*Last updated: YYYY-MM-DD*

| Sl. No | Task | Description | Category | Assigned to |
|--------|------|-------------|----------|-------------|
```

Rows use this status convention in the `Category` column when a task is done:

- Move the original category into the `Description` field if useful, and set `Category` to `Done`.
- Alternatively, append `✅ Done` at the end of the `Description` cell and keep the original category.

Default to the latter to minimize column shuffling.

## Rules

- Never delete rows unless the user explicitly says so.
- Do not renumber existing rows; always append new tasks with the next serial number.
- Keep descriptions short (one sentence or a single clause).
- If a task is already present, update its row rather than creating a duplicate.
- Only write to `Tasks.md`; do not commit or stage changes.

## Example invocation and result

Input:

```
/update-tasks Finished implementing the MCP server in src/mcp_server.py and wired it into main.py.
```

Resulting change in `Tasks.md`:

```markdown
| 5 | Implement MCP server | Exposes ingestion, extraction, upsert, and F1–F4 graph tools via FastMCP; wired into main.py. ✅ Done | Core feature | Claude |
```
