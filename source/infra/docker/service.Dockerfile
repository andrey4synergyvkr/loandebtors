# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ARG DISTRIBUTION=loandebtors-notifications
ARG SERVICE=notifications
ARG PORT=8001

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY source/services ./source/services

RUN uv sync --frozen --no-dev --package "${DISTRIBUTION}"

ENV ENVIRONMENT=production \
    OTEL_ENABLED=true \
    SERVICE_NAME=${SERVICE} \
    SERVICE_PORT=${PORT}

EXPOSE ${PORT}

CMD ["sh", "-c", "alembic -c source/services/${SERVICE_NAME}/alembic.ini upgrade head && uvicorn ${SERVICE_NAME}.main:app --host 0.0.0.0 --port ${SERVICE_PORT}"]
