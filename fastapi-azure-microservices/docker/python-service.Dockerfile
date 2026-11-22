# One hardened image recipe for every Python service.
#   docker build -f docker/python-service.Dockerfile \
#     --build-arg SERVICE=orders-service --build-arg SERVICE_MODULE=orders_service .
ARG PYTHON_VERSION=3.12

# ---------- build stage: resolve and install dependencies into a venv
FROM python:${PYTHON_VERSION}-slim AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

ARG SERVICE
# Copy the shared lib first so its layer is cached across services.
COPY libs/common /src/libs/common
COPY services/${SERVICE} /src/service
RUN pip install /src/libs/common /src/service

# ---------- runtime stage: no compilers, no source tree, non-root
FROM python:${PYTHON_VERSION}-slim AS runtime
ARG SERVICE
ARG SERVICE_MODULE
ARG GIT_SHA=dev
LABEL org.opencontainers.image.source="orderflow" \
      org.opencontainers.image.revision="${GIT_SHA}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_FACTORY="${SERVICE_MODULE}.main:create_app" \
    SERVICE_VERSION="${GIT_SHA}" \
    PORT=8000

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY services/${SERVICE}/alembic.ini ./alembic.ini
COPY services/${SERVICE}/migrations ./migrations
COPY docker/entrypoint.sh /entrypoint.sh

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health/live', timeout=2)" || exit 1

ENTRYPOINT ["sh", "/entrypoint.sh"]
