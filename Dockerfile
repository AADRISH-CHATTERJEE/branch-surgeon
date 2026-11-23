FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY refactory/ refactory/

RUN pip install --no-cache-dir -e ".[backend]"

VOLUME /data
ENV REFACTORY_DB_URL=sqlite:////data/refactory.db

ENTRYPOINT ["refactory"]
