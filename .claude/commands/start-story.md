---
description: Begin work on a specific story — move to In Progress, branch, plan tasks.
argument-hint: <story-id>  (e.g., S1.3)
allowed-tools: Read, Edit, Bash(git checkout:*), Bash(git branch:*), TodoWrite
---

# /start-story $1

Begin work on story `$1`.

## Steps

1. Find the story in `docs/product/user-stories.md` matching `$1`.
2. Move it from any other lane to **In Progress** in `docs/sprints/active.md`. If a card is already in progress, ask the user whether to swap or queue.
3. Create a git branch: `git checkout -b feat/$1-<short-slug>` (slug = first 3 words of the story, kebab-cased).
4. Generate a TodoWrite list from the story's acceptance criteria. Each criterion = one todo. Mark the first as `in_progress`.
5. Note any files the story will touch (from Technical Notes).
6. Don't START coding — wait for the user to confirm the plan.

## Output

```
▶️ Started story $1 — <title>

Branch: feat/$1-<slug>

Acceptance criteria → TodoWrite:
- [ ] <criterion 1> (in progress)
- [ ] <criterion 2>
- ...

Files likely touched:
- <path1>
- <path2>

→ Proceed?
```
