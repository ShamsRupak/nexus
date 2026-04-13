FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
RUN pip install uv

# Copy project files
COPY pyproject.toml .
COPY nexus/ nexus/

# Install dependencies
RUN uv pip install --system -e ".[dev]"

EXPOSE 8080

CMD ["uvicorn", "nexus.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
