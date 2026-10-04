.PHONY: help dev backend frontend test lint build up down

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

backend:   ## run the API on :8000
	cd backend && uvicorn app.api:app --reload --port 8000

frontend:  ## run the UI on :5173
	cd frontend && npm run dev

test:      ## run the backend test suite
	cd backend && pytest

lint:      ## ruff + tsc
	cd backend && ruff check .
	cd frontend && npm run typecheck

build:     ## production build of the UI
	cd frontend && npm run build

up:        ## docker compose up
	docker compose up --build

down:
	docker compose down
