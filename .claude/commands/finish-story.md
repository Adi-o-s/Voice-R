---
description: Close out a story — mark done, log learnings, propose commit.
argument-hint: <story-id>  (e.g., S1.3)
allowed-tools: Read, Edit, Bash(git diff:*), Bash(git log:*), Bash(git status:*), Bash(pytest:*)
---

# /finish-story $1

Wrap up story `$1`.

## Steps

1. Verify acceptance criteria — read the story in `docs/product/user-stories.md` and confirm every criterion is met. If any aren't, list what's missing and **stop**.
2. Run `pytest apps/voice-agent/tests` (if Python touched) — must pass.
3. Move the card to **Done** in `docs/sprints/active.md`. Append today's date next to the title.
4. Append a "Learnings" bullet to the sprint file (`docs/sprints/sprint-<n>-*.md`) — one line on what was surprising or worth remembering.
5. Fill in the story's Learnings section in user-stories.md.
6. Look at `git status` + `git diff` and propose a conventional-commit message:
   `feat($1): <imperative summary>` or `fix($1): ...` etc. Use a HEREDOC body if multiline.
7. **Do not commit** — show the user the proposed command and let them run it (avoids surprise commits per `CLAUDE.md` conventions).

## Output

```
✅ Story $1 closed.

DoD check: all <n>/<n> criteria met.
Tests: <pass/fail/n-a>.

Suggested commit:
git commit -m "feat($1): <summary>

<body>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

Learnings logged to: docs/sprints/sprint-<n>-<slug>.md
```
