# Dockerfile for running RepoLens in hosted (multi-tenant, streamable-http)
# mode. Local stdio use (Claude Desktop, etc.) doesn't need this at all -
# it's only for deploying RepoLens as a shared HTTP service.
#
# Build:
#   docker build -t repolens .
#
# Run (see README.md "Hosted deployment" for the full env var list):
#   docker run -p 8000:8000 \
#     -e REPOLENS_TRANSPORT=http \
#     -e REPOLENS_PUBLIC_URL=https://your-domain.example.com \
#     -e GITHUB_OAUTH_CLIENT_ID=... \
#     -e GITHUB_OAUTH_CLIENT_SECRET=... \
#     -v repolens-data:/data \
#     -e REPOLENS_SESSION_DB_PATH=/data/repolens_sessions.db \
#     repolens

FROM python:3.12-slim

WORKDIR /app

# Install the package (and its runtime deps) without dev/test extras.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Session data (SQLite) should live on a mounted volume so it survives
# container restarts/redeploys - mount a volume at /data and point
# REPOLENS_SESSION_DB_PATH at a file inside it (see run example above).
RUN mkdir -p /data
VOLUME ["/data"]

ENV REPOLENS_TRANSPORT=http
ENV REPOLENS_HOST=0.0.0.0
ENV REPOLENS_PORT=8000
ENV REPOLENS_SESSION_DB_PATH=/data/repolens_sessions.db

EXPOSE 8000

# REPOLENS_PUBLIC_URL, GITHUB_OAUTH_CLIENT_ID, and GITHUB_OAUTH_CLIENT_SECRET
# are required at runtime and have no safe defaults - pass them via your
# platform's environment/secrets configuration, not baked into the image.
CMD ["repolens"]
