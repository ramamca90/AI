# Incident Copilot

Python 3.12, FastAPI, async SQLAlchemy, Claude API. See `docs/ARCHITECTURE.md`.

## Commands
- Install: `uv sync`
- Test: `uv run pytest`
- Lint and types: `uv run ruff check . && uv run ruff format --check . && uv run mypy`

## Rules
- `src/copilot/domain/` is the shared contract. Don't change it without a reason you can state.
- LLM tools are read-only. Anything that changes production goes through `RemediationExecutor`.
- Never put timestamps, IDs or other per-request data in system prompts or tool lists: it
  breaks prompt caching. Sort anything serialized into a prompt.
- Append `LLMResponse.content` to history unchanged. Never edit earlier turns.
- Opus 5.5 returns a 400 on forced `tool_choice`, `thinking.disabled`, `budget_tokens` and
  sampling parameters. Use `auto`, structured outputs and `output_config.effort`.
- Tests run offline. A test must never call the real API or AWS.
