FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir anthropic python-dotenv
COPY app ./app
COPY sandbox ./sandbox
# Run as a non-root user.
RUN useradd -m bot && chown -R bot /app
USER bot
# Default: run one test case read from stdin (Sentinel's harness uses this).
# Each run copies sandbox/ to a temp folder, so the image itself is never changed.
CMD ["python", "-m", "app.run_case"]
