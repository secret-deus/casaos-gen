# Repository Guidelines

## Project Structure & Modules
- `fastmcp_k8s_service/`: Python package (entrypoint, Kubernetes helpers, metrics, config).
  - Notables: `main.py`, `k8s.py`, `metrics.py`, `config.py`.
- `frontend/`: Static UI assets (`index.html`, `app.js`, `styles.css`).
- `tests/`: Python unit tests (unittest style, `test_*.py`).
- `pyproject.toml`: Build and scripts (hatchling + uv).
- `requirements.txt`: Dependencies for pip users.

## Build, Test, and Run
- `uv run start`: Run service over HTTP (FastMCP transport).
- `uv run start-stdio`: Run service over stdio (agent embedding).
- `uv run test`: Run unit tests via `unittest` discovery.
- Without `uv`:
  - `python -m fastmcp_k8s_service.main --transport http`
  - `python -m unittest discover -s tests`

## Coding Style & Naming
- Python: PEP 8, 4-space indent; `snake_case` functions/vars, `PascalCase` classes, `SCREAMING_SNAKE_CASE` constants.
- Keep modules focused: Kubernetes logic in `k8s.py`, orchestration in `main.py`, metrics in `metrics.py`.
- Prefer small, typed functions (add `typing` where practical). Write clear docstrings for public functions.

## Testing Guidelines
- Framework: `unittest` with files named `test_*.py` under `tests/`.
- Structure: one test class per module; use fakes over live clusters where possible.
- Run: `uv run test` (or `python -m unittest discover -s tests`). Aim for meaningful coverage on k8s interactions.

## Commit & PR Guidelines
- Commits: Imperative mood and concise scope. Prefer Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`).
  - Example: `feat(k8s): add rollout status check`.
- PRs: Include summary, linked issues, steps to run, and screenshots/GIFs for UI changes. Note risks and rollback.

## Security & Configuration
- Kubernetes: Use a non-production context for local testing. Respect namespace boundaries.
- Config: Use `KUBECONFIG` or in-cluster config; never commit secrets or kubeconfig files.
- Frontend: Keep third-party assets minimal and pinned.

## Architecture Overview
- Entrypoint: CLI `fastmcp-k8s-service` → `fastmcp_k8s_service.main:main`.
- Transports: HTTP or stdio via FastMCP; metrics exposed from `metrics.py`.
