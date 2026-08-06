# syntax=docker/dockerfile:1

# Build the admin console once. The final image only contains its static files,
# not Node.js or the frontend dependency tree.
FROM node:24-bookworm-slim AS webui-builder

WORKDIR /build/webui
COPY webui/package.json webui/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY webui/ ./
RUN npm run build

# Compile Python packages in a separate stage so compilers and development
# headers do not increase the size or attack surface of the runtime image.
FROM python:3.13-slim-bookworm AS python-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       libmariadb-dev \
       libjpeg-dev \
       zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip wheel --wheel-dir=/wheels -r requirements.txt

FROM python:3.13-slim-bookworm AS runtime

LABEL org.opencontainers.image.authors="Expliyh"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_HOST=mariadb \
    DATABASE_PORT=3306 \
    DATABASE_NAME=your_database_name \
    DATABASE_USERNAME=your_username \
    DATABASE_PASSWORD=your_password \
    DATABASE_PREFIX=acgimg \
    AUTO_START_FRONTEND=0 \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libjpeg62-turbo \
       libmariadb3 \
       zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app \
    && adduser --system --ingroup app --home /app app

WORKDIR /app
COPY --from=python-builder /wheels /wheels
COPY requirements/requirements.txt ./requirements/requirements.txt
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels \
      -r requirements/requirements.txt \
    && rm -rf /wheels

COPY --chown=app:app . .
COPY --from=webui-builder --chown=app:app /build/webui/dist ./webui/dist
RUN mkdir -p /app/storage /app/logs && chown -R app:app /app/storage /app/logs

USER app
VOLUME /app/storage
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)"]

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
