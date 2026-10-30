# ML Pipeline Formative 1

Hourly cryptocurrency pipeline for Gemini `BTCUSD`, `ETHUSD`, and `LTCUSD` minute bars (1 January 2020 through 20 April 2021). The notebook aggregates those minutes to hourly OHLCV bars, answers the analytical questions, and selects a forecast of the next Bitcoin close. The databases store the same hourly bars in MySQL and MongoDB.

The validation winner is a persistence forecast: the next close equals the current close. The notebook writes that estimator and its feature order under `model/`.

## Repository layout

```text
.
├── README.md
├── Dockerfile
├── docker-compose.yml
├── Pipfile
├── data/                          # Raw 1-minute Gemini CSVs (read-only, Git LFS)
├── notebook/eda.ipynb             # Exploration, questions, and model comparison
├── model/
│   ├── persistence_model.pkl      # Saved winner
│   └── feature_order.pkl          # ["close"]
├── database/
│   ├── data/                      # Hourly bars and outage intervals derived from data/
│   ├── erd/                       # ERD image and Workbench notes
│   ├── sql/                       # MySQL schema, loader, queries, Prisma schema
│   ├── mongo/                     # MongoDB design, loader, queries, Prisma schema
│   ├── seed_and_query.sh          # Schema, loaders, and saved query output
│   └── results/                   # mysql_queries.txt and mongo_queries.txt
├── src/database/clients.py        # MySQL and MongoDB Prisma clients
├── src/main.py                    # FastAPI app
└── generated/                     # prisma generate output (not committed)
```

Design notes that stay next to the databases:

- [database/erd/README.md](database/erd/README.md) explains the relational diagram in [database/erd/erd.png](database/erd/erd.png).
- [database/mongo/README.md](database/mongo/README.md) documents the collection design and sample documents.

## Setup

### Docker

Install Docker, then from the repository root pull the raw minute files and start the databases. `data/` is stored in Git LFS.

```bash
git lfs pull
docker compose up --build
```

Compose starts MySQL 8 on `localhost:3307` and MongoDB 7 on `localhost:27017`, both with database `crypto_pipeline`. The host port is 3307 so it does not collide with a MySQL server already bound to 3306. Inside the Compose network the MySQL port is still 3306. The root password is `password`. The `seed` service waits until both are healthy, applies `database/sql/schema.sql`, loads the hourly bars and outages, runs the query files, and exits. Inside that container the hosts are `mysql` and `mongo`, not `localhost`.

Query output is written to:

- `database/results/mysql_queries.txt`
- `database/results/mongo_queries.txt`

Running `docker compose up` again drops the MySQL tables and reloads both databases, because `schema.sql` drops the tables before the loaders run. The `api` service starts after that seed finishes and listens on `http://localhost:8000`. Interactive docs are at `http://localhost:8000/docs`.

Hourly bars have the same six operations on MySQL and MongoDB. Replace `mysql` with `mongo` for the second database.

| Method | Path | Action |
|---|---|---|
| POST | `/api/mysql/bars` | Create a bar |
| GET | `/api/mysql/bars/{bar_id}` | Read one bar |
| PUT | `/api/mysql/bars/{bar_id}` | Update a bar |
| DELETE | `/api/mysql/bars/{bar_id}` | Delete a bar |
| GET | `/api/mysql/bars/latest?symbol=BTCUSD` | Newest bar for a symbol |
| GET | `/api/mysql/bars?symbol=BTCUSD&start=2021-01-01T00:00:00&end=2021-01-01T06:00:00` | Bars in an inclusive time range |

The create body uses `symbol`, `timestamp`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`, and `minute_count`. A repeated symbol and hour returns 409. An unknown symbol or missing bar returns 404. Range results are oldest first and limited to 1000 rows unless `limit` is set.

### Pipenv

Install [Pipenv](https://pipenv.pypa.io/), then from the repository root:

```bash
pipenv install
pipenv shell
```

Copy the environment template and fill in the database URLs before generating clients or loading data:

```bash
cp .env.example .env
```

`MYSQL_DATABASE_URL` is the Prisma MySQL URL (`mysql://root:password@localhost:3307/crypto_pipeline`). The PyMySQL loader reads `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_DB`, and `MYSQL_PASSWORD`. `MONGODB_DATABASE_URL` is used by Prisma. The PyMongo loader reads `MONGO_URI` and `MONGO_DB`, and defaults to `mongodb://localhost:27017/` and database `crypto_pipeline`. The Prisma Mongo URL is `mongodb://localhost:27017/crypto_pipeline?directConnection=true`. Those localhost values match the published Compose ports. The seed container sets the same variables to the `mysql` and `mongo` service names and does not read `.env`.

Generate the Prisma clients after `.env` exists:

```bash
pipenv run generate-mysql
pipenv run generate-mongo
```

## Notebook and saved model

`notebook/eda.ipynb` resamples the minute files to hourly bars, keeps exchange outages out of the price series, and compares persistence with tuned ridge and histogram gradient boosting models. Persistence has the lowest validation MAE.

The cell after that selection writes:

- `model/persistence_model.pkl`
- `model/feature_order.pkl`, which is the list `["close"]`

Re-run the notebook from the `notebook/` directory to regenerate both files. The save cell refuses to write them if the validation winner is no longer persistence.

## Databases

MySQL and MongoDB both hold the hourly bars and the 23-hour exchange outages. MySQL also has a `symbols` lookup table and a `predictions` table. The cleaned exports in `database/data/` are what the loaders insert: **32,961** hourly bars (10,987 per coin) and **54** outages (18 per coin).

### Services

1. MySQL 8 from Compose on `localhost:3307`. The server inside the container listens on 3306.
2. MongoDB 7 on `localhost:27017`. Prisma writes need a replica set, so Compose starts MongoDB as the single-node set `rs0`. The Prisma URL adds `directConnection=true`.

### Create the MySQL schema

In MySQL Workbench, open `database/sql/schema.sql` and execute it. From a shell with the `mysql` client on `PATH`:

```bash
mysql -u root -p < database/sql/schema.sql
```

### Load MySQL

The loader reads the raw minute CSVs in `data/`, resamples them, writes `database/data/*.csv`, and bulk-loads MySQL. It does not modify the raw files.

```bash
export MYSQL_PASSWORD="your_mysql_password"
pipenv run python database/sql/load_mysql.py
```

If `MYSQL_PASSWORD` is unset, the script prompts for it. Expect **32,961** rows in `hourly_bars` and **54** rows in `data_gaps`.

### Load MongoDB

```bash
pipenv run python database/mongo/load_mongo.py
```

Expect **32,961** documents in `hourly_bars` and **54** documents in `data_gaps`.

### Queries

Open `database/sql/queries.sql` in MySQL Workbench, or run the MongoDB suite:

```bash
pipenv run python database/mongo/queries.py
```

Each file has five queries: latest bar per symbol, a Bitcoin date range, a monthly summary, the highest-volume hour per symbol, and the price jump across the first Bitcoin outages.

### MySQL schema (`crypto_pipeline`)

| Table | Role | Primary key | Keys |
| :--- | :--- | :--- | :--- |
| `symbols` | Lookup | `symbol_id INT AUTO_INCREMENT` | `UNIQUE (symbol_code)` |
| `hourly_bars` | Hourly OHLCV | `bar_id BIGINT AUTO_INCREMENT` | `UNIQUE (symbol_id, bar_time)`, `INDEX (bar_time)`, foreign key to `symbols` |
| `data_gaps` | Exchange outages | `gap_id INT AUTO_INCREMENT` | `UNIQUE (symbol_id, gap_start)`, `INDEX (gap_start, gap_end)`, foreign key to `symbols` |
| `predictions` | Forecast storage | `prediction_id BIGINT AUTO_INCREMENT` | `UNIQUE (symbol_id, target_time, model_version)`, `INDEX (target_time)`, foreign key to `symbols` |

Prices use `DECIMAL(18, 4)` and volume uses `DECIMAL(24, 8)`. Bar timestamps are `DATETIME` in UTC. Foreign keys use `ON DELETE RESTRICT` and `ON UPDATE CASCADE`.

### MongoDB collections (`crypto_pipeline`)

| Collection | Document | Natural key | Indexes |
| :--- | :--- | :--- | :--- |
| `hourly_bars` | One hour per document | `(symbol, timestamp)` | unique `{ symbol: 1, timestamp: 1 }`, `{ timestamp: 1 }` |
| `data_gaps` | One outage per document | `(symbol, gap_start)` | unique `{ symbol: 1, gap_start: 1 }` |

Timestamps are BSON `Date` values in UTC. The symbol code is stored on each document, so reads do not join a lookup collection.

### Prisma clients

`database/sql/prisma/schema.prisma` and `database/mongo/prisma/schema.prisma` describe those tables and collections. `pipenv run generate-mysql` and `pipenv run generate-mongo` write clients to `generated/mysql_client` and `generated/mongo_client`. [src/database/clients.py](src/database/clients.py) constructs one client for each database. The PyMySQL and PyMongo loaders are unchanged.

### API field mapping

| MySQL column | MongoDB field | JSON key | Meaning |
| :--- | :--- | :--- | :--- |
| `bar_id` | `_id` | `id` / `bar_id` | Record id |
| `symbols.symbol_code` | `symbol` | `symbol` | `BTCUSD`, `ETHUSD`, or `LTCUSD` |
| `bar_time` | `timestamp` | `timestamp` | Hour start, UTC |
| `open_price` | `open_price` | `open_price` | First trade in the hour |
| `high_price` | `high_price` | `high_price` | Highest trade in the hour |
| `low_price` | `low_price` | `low_price` | Lowest trade in the hour |
| `close_price` | `close_price` | `close_price` | Last trade in the hour |
| `volume` | `volume` | `volume` | Volume over the hour |
| `minute_count` | `minute_count` | `minute_count` | Minutes present in the hour (1 to 60) |

PyMySQL returns `DECIMAL` columns as `Decimal`. Convert those values to `float` or `str` before JSON encoding. Both databases reject a second bar for the same symbol and hour. Timestamps are UTC. The last bar, `2021-04-20 00:00:00`, is a partial hour (`minute_count` 3 for Bitcoin and 4 for Ether and Litecoin). Other hours in the series are partial as well, so keep `minute_count` on every payload.

## Prediction script (Task 4)

`src/predict.py` fetches the latest hourly bars from the API, applies the same cleaning as the notebook (hourly index, numeric types, gaps of up to 2 hours filled with the previous close), loads `model/persistence_model.pkl` and `model/feature_order.pkl`, and prints the next-hour close forecast.

Start the API first (`docker compose up --build -d`), then from the repository root:

```bash
pip install -r requirements-predict.txt
python src/predict.py                  # MySQL endpoints
python src/predict.py --source mongo   # MongoDB endpoints
```

Options: `--symbol BTCUSD`, `--hours 24` (history to fetch), `--url http://localhost:8000`. Sample output is in `docs/`.