---
description: Summarize the active sprint and propose the next 3 tasks.
allowed-tools: Read, Bash, TodoWrite
---

# /standup

You're starting a new working session. Read the current state and orient.

## Steps

1. Read `docs/sprints/active.md` — the live Kanban board.
2. Read `docs/CLAUDE.md` if you haven't this session.
3. In 3 bullets, summarize:
   - **Where we left off** (most recent done card, most recent daily-log entry)
   - **What's in progress** (any cards in the "In Progress" lane)
   - **What's next** (top 3 from "Backlog")
4. Ask the user which one to start, OR if a "in progress" card needs to be finished first, suggest that.
5. Do NOT start any work until the user picks.

## Output format

```
🏁 Standup — Sprint <n>: <goal>

Yesterday/last session:
- <bullet>

In progress:
- <bullet or "nothing">

Next up (top 3 from backlog):
1. <story id> — <title> (est <hrs>h)
2. ...
3. ...

→ Which do you want to start?
```
