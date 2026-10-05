# Use a small Python image so the same container works for the API and workers.
FROM python:3.11-slim

# Make Python logs appear immediately in Docker logs.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# All commands below run from the application directory.
WORKDIR /app

# libpq5 is required by the PostgreSQL driver at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first so Docker can reuse the pip-install layer.
COPY requirements /app/requirements
RUN pip install --no-cache-dir -r /app/requirements/base.txt

# Copy the Django source code into the image.
COPY . /app

# Run the process as an unprivileged user.
RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/media /app/staticfiles \
    && chown -R app:app /app

USER app
