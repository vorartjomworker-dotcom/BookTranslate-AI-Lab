FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt

RUN addgroup --system booktranslate \
    && adduser --system --ingroup booktranslate --home /home/booktranslate booktranslate \
    && mkdir -p /var/lib/booktranslate/uploads \
    && chown -R booktranslate:booktranslate /var/lib/booktranslate /home/booktranslate

COPY --chown=booktranslate:booktranslate alembic.ini ./alembic.ini
COPY --chown=booktranslate:booktranslate alembic ./alembic
COPY --chown=booktranslate:booktranslate app ./app

USER booktranslate

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
