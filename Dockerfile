# syntax=docker/dockerfile:1
FROM node:24.13.0-slim AS visuals
WORKDIR /visuals
COPY visuals/package*.json ./
RUN npm ci --omit=dev
COPY visuals/ ./
RUN npm install --prefix /build-tools esbuild@0.28.2 \
    && ln -s /build-tools/node_modules/esbuild node_modules/esbuild \
    && npm run build

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/opt/clipz-browsers

# ffmpeg/ffprobe for media work + curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl fonts-liberation fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /srv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project --extra showcase \
    && uv run --no-sync playwright install --with-deps chromium

COPY app ./app
COPY --from=visuals /visuals/dist ./visuals/dist
COPY --from=visuals /visuals/src ./visuals/src
COPY --from=visuals /visuals/package-lock.json ./visuals/package-lock.json
RUN uv sync --frozen --no-dev --extra showcase

# Non-root runtime
RUN useradd -m -u 10001 appuser && mkdir -p /srv/tmp /srv/data && chown -R appuser /srv
USER appuser

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
