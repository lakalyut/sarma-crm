FROM python:3.11-slim AS dependencies

WORKDIR /app

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --only-binary=:all: --no-cache-dir --no-compile -r requirements.txt

FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=dependencies /opt/venv /opt/venv
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini release_updates.json ./

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
