#!/usr/bin/env bash
set -euo pipefail

cd /app

echo "Applying MySQL schema..."
mysql \
  --protocol=TCP \
  --host="$MYSQL_HOST" \
  --port="$MYSQL_PORT" \
  --user="$MYSQL_USER" \
  --password="$MYSQL_PASSWORD" \
  --skip-ssl \
  < database/sql/schema.sql

echo "Loading MySQL from the raw minute files..."
python database/sql/load_mysql.py

echo "Loading MongoDB..."
python database/mongo/load_mongo.py

mkdir -p database/results

echo "Running MySQL queries..."
mysql \
  --protocol=TCP \
  --host="$MYSQL_HOST" \
  --port="$MYSQL_PORT" \
  --user="$MYSQL_USER" \
  --password="$MYSQL_PASSWORD" \
  --skip-ssl \
  --table \
  < database/sql/queries.sql \
  > database/results/mysql_queries.txt

echo "Running MongoDB queries..."
python database/mongo/queries.py > database/results/mongo_queries.txt

echo "Seed complete. Query results are in database/results/."
