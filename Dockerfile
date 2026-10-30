FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends default-mysql-client nodejs npm libatomic1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pipenv

WORKDIR /app

COPY Pipfile Pipfile.lock ./
RUN pipenv install --system --deploy