FROM python:3.12-slim

LABEL maintainer="Khalil Limem"
LABEL org.opencontainers.image.source="https://github.com/khalil/coderev"
LABEL org.opencontainers.image.description="AI-powered code review GitHub Action"

# Install git and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy package files first for better caching
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Install the package with all optional dependencies
RUN pip install --no-cache-dir ".[all]"

# Copy the entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set the entrypoint
ENTRYPOINT ["/entrypoint.sh"]
