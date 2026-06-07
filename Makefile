# Voice AI Receptionist — developer commands
# Run `make help` to see all targets.

.PHONY: help voice dash tunnel sql-apply seed test stress probe fmt lint clean install setup

PYTHON := ~/.local/bin/uv run
NGROK_PORT := 8000
DASH_PORT := 3000

help:
	@echo "Voice AI Receptionist — make targets"
	@echo ""
	@echo "  setup        Install all deps (uv + pnpm)"
	@echo "  voice        Run voice-agent (FastAPI :8000) + ngrok in the background"
	@echo "  dash         Run Next.js dashboard (:3000)"
	@echo "  tunnel       Start ngrok pointing at :8000 (voice already running)"
	@echo "  sql-apply    Apply infra/supabase/*.sql to SUPABASE_DB_URL"
	@echo "  seed         Apply 002_seed_acme.sql only"
	@echo "  test         Pytest apps/voice-agent/tests"
	@echo "  stress       Real-API load test (CALLS=3 TURNS=4) — LLM failover + no-dead-air"
	@echo "  probe        Hammer Groq with the real payload, print rate-limit headers"
	@echo "  fmt          ruff --fix + black + prettier"
	@echo "  lint         ruff check + prettier --check"
	@echo "  clean        Remove .venv, .next, __pycache__"

setup:
	cd apps/voice-agent && uv sync
	corepack enable pnpm
	cd apps/dashboard && pnpm install

voice:
	cd apps/voice-agent && $(PYTHON) uvicorn src.main:app --reload --port $(NGROK_PORT)

dash:
	cd apps/dashboard && pnpm dev --port $(DASH_PORT)

tunnel:
	ngrok http $(NGROK_PORT)

sql-apply:
	@test -n "$$SUPABASE_DB_URL" || (echo "❌ SUPABASE_DB_URL not set"; exit 1)
	psql "$$SUPABASE_DB_URL" -f infra/supabase/001_init.sql
	psql "$$SUPABASE_DB_URL" -f infra/supabase/002_seed_acme.sql

seed:
	@test -n "$$SUPABASE_DB_URL" || (echo "❌ SUPABASE_DB_URL not set"; exit 1)
	psql "$$SUPABASE_DB_URL" -f infra/supabase/002_seed_acme.sql

test:
	cd apps/voice-agent && $(PYTHON) pytest -q

CALLS ?= 3
TURNS ?= 4

stress:
	cd apps/voice-agent && $(PYTHON) python scripts/stresstest.py --mode load --calls $(CALLS) --turns $(TURNS)

probe:
	cd apps/voice-agent && $(PYTHON) python scripts/stresstest.py --mode probe --calls $(CALLS)

fmt:
	cd apps/voice-agent && uv run ruff check --fix . || true
	cd apps/voice-agent && uv run black .
	cd apps/dashboard && pnpm exec prettier --write .

lint:
	cd apps/voice-agent && uv run ruff check .
	cd apps/dashboard && pnpm exec prettier --check .

clean:
	rm -rf apps/voice-agent/.venv apps/voice-agent/.pytest_cache
	find apps/voice-agent -name __pycache__ -type d -exec rm -rf {} +
	rm -rf apps/dashboard/.next apps/dashboard/node_modules
