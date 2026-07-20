# justfile — common AnkleFlex development tasks

default:
    @just --list

# Install runtime + dev dependencies (editable package)
sync:
    uv sync --extra dev

# Install with Raspberry Pi hardware dependencies
sync-hardware:
    uv sync --extra dev --extra hardware

lint:
    uv run ruff check .

format:
    uv run ruff format .

test:
    uv run pytest

coverage:
    uv run pytest --cov=Src --cov-report=term-missing

test-unit:
    uv run pytest -m "not integration"

test-integration:
    uv run pytest -m integration

check:
    uv run pre-commit run --all-files

secrets:
    detect-secrets scan > .secrets.baseline

audit:
    uv run pip-audit

# Run the server (emulation is automatic without Pi hardware)
run:
    uv run python Src/main.py

# Alias for local dev without hardware — same as run on non-Pi machines
mock: run
