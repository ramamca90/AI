# One image, two processes: the default command is copilot-api. ECS and compose override it
# with copilot-worker or `alembic upgrade head`.
#
# There is deliberately no HEALTHCHECK here: it would also apply to the worker, which serves
# no HTTP. The ALB checks /readyz in AWS, and docker-compose.yml probes /healthz on the api.

# Base image and uv are pinned by tag and digest. Keep the two FROM lines identical: the venv
# built in the first stage points at this interpreter.
FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so a source change does not reinstall them.
# README.md is needed because pyproject.toml names it as the package readme.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS runtime

# API_HOST: the app binds to 127.0.0.1 by default, which no ALB or published port can reach.
ENV PATH="/app/.venv/bin:$PATH" \
    API_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 copilot \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin copilot

WORKDIR /app

# Root-owned and read-only to the app user. src/ is not copied: it is installed in the venv.
COPY --from=builder /app/.venv ./.venv
COPY alembic.ini ./
COPY migrations ./migrations

USER 10001:10001
EXPOSE 8000
CMD ["copilot-api"]
