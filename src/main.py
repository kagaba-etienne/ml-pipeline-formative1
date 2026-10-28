from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.mongo_bars import router as mongo_bars_router
from src.api.mysql_bars import router as mysql_bars_router
from src.database.clients import mongo_client, mysql_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    await mysql_client.connect()
    await mongo_client.connect()
    yield
    await mysql_client.disconnect()
    await mongo_client.disconnect()


app = FastAPI(
    title="Crypto hourly bars",
    description="CRUD and time-series reads for hourly bars in MySQL and MongoDB.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(mysql_bars_router)
app.include_router(mongo_bars_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Crypto hourly bars API"}
