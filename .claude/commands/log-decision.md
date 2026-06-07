---
description: Create a new ADR (Architecture Decision Record).
argument-hint: <short-slug>  (e.g., "smart-endpointing")
allowed-tools: Read, Write, Bash(ls:*)
---

# /log-decision $1

Scaffold a new ADR.

## Steps

1. List existing ADRs: `ls docs/decisions/`
2. Pick the next NNN (zero-padded 3 digits).
3. Create `docs/decisions/NNN-$1.md` from this template:

```markdown
# ADR-NNN: <Title — what we chose, one line>

> Status: **Proposed** | Accepted | Superseded by [[ADR-MMM]]
> Date: <YYYY-MM-DD>
> Project: [[../CLAUDE]]

## Context

<What problem are we solving? What forces are at play?>

## Decision

<What did we choose, in one sentence? Then 3–5 bullets.>

## Alternatives Considered

| Option | Pros | Cons | Why not |
|---|---|---|---|

## Consequences

- **Positive:**
- **Negative:**
- **Neutral / accepted:**

## Follow-ups

- [ ] 
```

4. Open the file so the user can fill in the content.

## Output

```
🧠 ADR-NNN created at docs/decisions/NNN-$1.md

→ Fill in Context / Decision / Alternatives / Consequences.
```
