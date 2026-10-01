FROM python:3.12-slim

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl git build-essential whois \
    && pip install --no-cache-dir uv==0.9.26 patchright==1.58.0 \
    && patchright install-deps chromium \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/apt/lists/* \
    && rm -rf /var/cache/apt/*

# Create a non-root user
RUN useradd -m -s /bin/bash appuser

# Switch to non-root user
USER appuser

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONDONTWRITEBYTECODE=True \
    PYTHONUNBUFFERED=True \
    PYTHONIOENCODING=utf-8 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH:/home/appuser/.local/bin

# Copy local code to the container image.
ENV APP_HOME /app
WORKDIR $APP_HOME

COPY . $APP_HOME/

# Chromium for the patchright excavators, installed as appuser so it lands in
# /home/appuser/.cache/ms-playwright where _detect_patchright_chrome_path()
# finds it at runtime (issue #95: browser excavators were dead in the image)
RUN uv sync --frozen --no-dev --extra vision \
    && patchright install chromium

# Headed mode is unusable in-container (no X server)
ENV THEDIG_PATCHRIGHT_HEADLESS=true

EXPOSE 8080

# Add HEALTHCHECK instruction
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/docs || exit 1


# Run the web service on container startup. Here we use uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--proxy-headers", "--use-colors", "--port", "8080"]
