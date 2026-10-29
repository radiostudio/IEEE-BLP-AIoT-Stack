# AIoT gateway image. Built on the target (Uno Q: linux/arm64) with
#   docker compose up -d --build
# See compose.yaml for how it is run, and gateway/README.md "Docker".
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg

WORKDIR /app

# dependencies first, so code edits rebuild in seconds; requirements-docker.txt
# adds the analysis libraries (pandas, polars, matplotlib, ...) to requirements.txt
COPY gateway/requirements.txt gateway/requirements-docker.txt gateway/
RUN pip install -r gateway/requirements-docker.txt

COPY gateway/ gateway/
COPY docker/entrypoint.sh /usr/local/bin/gateway-entrypoint
RUN chmod +x /usr/local/bin/gateway-entrypoint

ENTRYPOINT ["gateway-entrypoint"]
CMD ["run"]
