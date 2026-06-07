---
description: Write a sprint retrospective from the daily log and completed stories.
allowed-tools: Read, Edit, Bash(git log:*)
---

# /retro

Generate a retrospective for the currently-active sprint.

## Steps

1. Read `docs/sprints/active.md` — extract the sprint number, daily log entries, and "Done" cards.
2. Read `git log` since sprint start for the actual commit history.
3. Cross-reference: any "Done" cards that have no commit? Any commits not tied to a story?
4. Write the Retro section in three buckets:
   - **Went well** — 2–3 specific things (cite story IDs or commits).
   - **Didn't go well** — 1–3 specific frictions or surprises.
   - **One change next sprint** — one actionable, narrow change.
5. Also update Metrics section: stories planned, stories completed, carry-over count, hours spent.
6. Mark the sprint `status: closed` in the frontmatter.
7. Update the `active.md` symlink/file to point at the next sprint.
8. **Do not** invent feelings the user didn't express — ask them to review the draft.

## Output

```
🪞 Sprint <n> retro drafted.

Stories: <completed>/<planned> ・ Carry-over: <n>

Went well:
- ...

Didn't go well:
- ...

Next change:
- ...

→ Review and edit; I won't close the sprint until you say so.
```
