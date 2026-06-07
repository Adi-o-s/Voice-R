---
description: Roll up per-stage latency from recent calls and compare against the HLD budget.
allowed-tools: Read, Bash(curl:*), Bash(uv run:*)
---

# /latency-check

Surface per-stage latency violators.

## Steps

1. Read the latency budget from `docs/HLD.md` § Latency Budget.
2. Query Supabase for the last 20 transcripts:
   ```python
   uv run python -c "
   from src.db import supa
   import statistics as st
   rows = supa.table('transcripts').select('stt_latency_ms, llm_latency_ms, tts_latency_ms').order('id', desc=True).limit(20).execute().data
   for k in ['stt', 'llm', 'tts']:
       vals = [r[f'{k}_latency_ms'] for r in rows if r.get(f'{k}_latency_ms')]
       if vals:
           print(f'{k}: median={st.median(vals)}ms p95={sorted(vals)[int(len(vals)*0.95)]}ms')
   "
   ```
3. Compare each median against budget. Red if median > budget, amber if p95 > budget, green otherwise.
4. Recommend the cheapest fix if anything is red (e.g., "TTS over budget — consider switching to Cartesia Sonic which advertises 90ms first-byte").

## Output

```
⏱  Latency check — last 20 turns

Stage   Median   p95     Budget   Status
STT     142ms    198ms   150ms    🟢
LLM     283ms    412ms   250ms    🟡 (p95 over)
TTS     217ms    298ms   200ms    🟡

Recommendation: …
```
