.PHONY: up down clean psi setup-a setup-b logs

# ── Docker ───────────────────────────────────────────────────────────────────

up:
	docker compose up --build

up-d:
	docker compose up --build -d

down:
	docker compose down

clean:
	docker compose down -v
	rm -f company_a/data/initiator.db company_b/data/receiver.db
	rm -f company_a/ap3_keys.json company_b/ap3_keys.json

logs:
	docker compose logs -f

psi-docker:
	docker compose exec company_a uv run psi_client.py

# ── Local ─────────────────────────────────────────────────────────────────────

setup-a:
	cd company_a && uv lock && uv sync

setup-b:
	cd company_b && uv lock && uv sync

setup: setup-b setup-a

# Start both servers in background, then run PSI
psi-local:
	@echo "Starting Company B (receiver)..."
	cd company_b && uv run . &
	@sleep 2
	@echo "Starting Company A (initiator)..."
	cd company_a && uv run . &
	@sleep 2
	@echo "Running PSI..."
	cd company_a && uv run psi_client.py
