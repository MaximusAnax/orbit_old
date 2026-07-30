# Single deployable unit: recorder + trading loop + dashboard in one process.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[analysis]"

# Never run as root; the container holds trading credentials.
RUN useradd --create-home --uid 10001 orbit \
    && mkdir -p /app/data /app/secrets \
    && chown -R orbit:orbit /app
USER orbit

VOLUME ["/app/data"]
EXPOSE 8080

# Default to the recorder: it is the component that should always be running,
# and it can never place an order.
CMD ["orbit", "record"]
