# Official Playwright image: browsers + OS deps preinstalled, version-matched to the library.
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SCRAPER_LOG_JSON=true

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && playwright install chromium

# Run as the non-root user shipped with the image.
USER pwuser
ENTRYPOINT ["scraper"]
CMD ["books", "--max-pages", "1"]
