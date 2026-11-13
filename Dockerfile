# =============================================================
# One Rupee — Production Container
# =============================================================
# Builds a minimal image that can generate PDF certificates
# (Playwright + Chromium) and serve the FastAPI application.
# =============================================================

FROM python:3.13-slim AS runtime

WORKDIR /app

# ------------------------------------------------------------------
# 1. Install Python dependencies first (layer caching optimisation).
#    Only pyproject.toml is needed for the pip install step.
# ------------------------------------------------------------------
COPY pyproject.toml .

# Stub the packages so `pip install .` can resolve the project
# metadata before the full source is copied.
RUN mkdir -p backend one_rupee \
    && touch backend/__init__.py one_rupee/__init__.py \
    && pip install --no-cache-dir .

# ------------------------------------------------------------------
# 2. Install Playwright Chromium and its OS-level dependencies.
#    --with-deps installs the required system libraries (libnss3,
#    libatk, libcups, fonts, etc.) automatically on Debian.
#    PLAYWRIGHT_BROWSERS_PATH stores the browser in a shared
#    location accessible to the non-root runtime user.
# ------------------------------------------------------------------
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

RUN playwright install --with-deps chromium

# ------------------------------------------------------------------
# 3. Copy application source.
# ------------------------------------------------------------------
COPY backend/ backend/
COPY one_rupee/ one_rupee/

# Re-install so setuptools picks up the real package contents
# (static HTML, package metadata). The dependencies are already
# cached, so this is near-instant.
RUN pip install --no-cache-dir .

# ------------------------------------------------------------------
# 4. Create a non-root user for runtime security.
# ------------------------------------------------------------------
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /opt/ms-playwright

USER appuser

# ------------------------------------------------------------------
# 5. Start the FastAPI server.
#    Render injects PORT (default 10000).  The app reads
#    ONE_RUPEE_BASE_URL for public-facing URLs, so the internal
#    port only matters for binding.
# ------------------------------------------------------------------
EXPOSE 10000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
