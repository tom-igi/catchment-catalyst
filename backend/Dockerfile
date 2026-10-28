# One image for all of the Python backend: the schema tool now, and later the
# admin API and import worker. Each service chooses its own command, so the
# same image runs locally (Docker Compose) and in Azure (Container Apps).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 1000 app

COPY requirements.txt .
RUN pip install -r requirements.txt
COPY catalyst ./catalyst

# Development image: adds the test tools and tests.
FROM base AS dev
COPY requirements-dev.txt pytest.ini ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
USER app

# Production image (the default build target).
FROM base AS prod
USER app
