FROM python:3.12-slim

WORKDIR /app

# Install build deps for lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Install pip dependencies before copying source (better layer caching)
COPY pyproject.toml README.md ./
# Create minimal package stub so pip -e works
RUN mkdir -p ryanair_tracker && touch ryanair_tracker/__init__.py
RUN pip install --no-cache-dir -e .

# Copy full source
COPY ryanair_tracker/ ./ryanair_tracker/

# Persistent data lives in a volume mounted at /app/data
# schedules.json also lives in /app (project root) — override via SCHEDULES_FILE env var
ENV SCHEDULES_FILE=/app/data/schedules.json

CMD ["ryanair-bot"]
