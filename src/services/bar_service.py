from datetime import datetime, timezone
from typing import Any, Literal

from generated.mongo_client.errors import UniqueViolationError as MongoUniqueViolation
from generated.mysql_client.errors import UniqueViolationError as MySQLUniqueViolation
from prisma.errors import UniqueViolationError

from src.schemas.bars import BarCreate, BarResponse, BarUpdate

Engine = Literal["mysql", "mongo"]
UNIQUE_ERRORS = (UniqueViolationError, MySQLUniqueViolation, MongoUniqueViolation)


class UnknownSymbol(Exception):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(symbol)


class BarNotFound(Exception):
    def __init__(self, bar_id: str) -> None:
        self.bar_id = bar_id
        super().__init__(bar_id)


class DuplicateBar(Exception):
    pass


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0)


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


class BarService:
    def __init__(self, db: Any, engine: Engine) -> None:
        self.db = db
        self.engine = engine

    async def create_bar(self, data: BarCreate) -> BarResponse:
        try:
            if self.engine == "mysql":
                return await self._create_mysql(data)
            return await self._create_mongo(data)
        except UNIQUE_ERRORS as exc:
            raise DuplicateBar from exc

    async def get_bar(self, bar_id: str) -> BarResponse:
        if self.engine == "mysql":
            record = await self._mysql_by_id(bar_id)
            return self._from_mysql(record)
        record = await self._mongo_by_id(bar_id)
        return self._from_mongo(record)

    async def update_bar(self, bar_id: str, data: BarUpdate) -> BarResponse:
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            return await self.get_bar(bar_id)
        try:
            if self.engine == "mysql":
                return await self._update_mysql(bar_id, data)
            return await self._update_mongo(bar_id, data)
        except UNIQUE_ERRORS as exc:
            raise DuplicateBar from exc

    async def delete_bar(self, bar_id: str) -> None:
        if self.engine == "mysql":
            parsed = self._mysql_id(bar_id)
            await self._mysql_by_id(bar_id)
            await self.db.hourly_bars.delete(where={"bar_id": parsed})
            return
        await self._mongo_by_id(bar_id)
        await self.db.hourly_bars.delete(where={"id": bar_id})

    async def latest_bar(self, symbol: str) -> BarResponse:
        if self.engine == "mysql":
            symbol_row = await self._mysql_symbol(symbol)
            record = await self.db.hourly_bars.find_first(
                where={"symbol_id": symbol_row.symbol_id},
                order={"bar_time": "desc"},
                include={"symbols": True},
            )
            if record is None:
                raise BarNotFound(symbol)
            return self._from_mysql(record)
        record = await self.db.hourly_bars.find_first(
            where={"symbol": symbol},
            order={"timestamp": "desc"},
        )
        if record is None:
            raise BarNotFound(symbol)
        return self._from_mongo(record)

    async def bars_in_range(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[BarResponse]:
        if self.engine == "mysql":
            symbol_row = await self._mysql_symbol(symbol)
            records = await self.db.hourly_bars.find_many(
                where={
                    "symbol_id": symbol_row.symbol_id,
                    "bar_time": {
                        "gte": _as_naive_utc(start),
                        "lte": _as_naive_utc(end),
                    },
                },
                order={"bar_time": "asc"},
                take=limit,
                include={"symbols": True},
            )
            return [self._from_mysql(record) for record in records]
        records = await self.db.hourly_bars.find_many(
            where={
                "symbol": symbol,
                "timestamp": {
                    "gte": _as_aware_utc(start),
                    "lte": _as_aware_utc(end),
                },
            },
            order={"timestamp": "asc"},
            take=limit,
        )
        return [self._from_mongo(record) for record in records]

    async def _create_mysql(self, data: BarCreate) -> BarResponse:
        symbol_row = await self._mysql_symbol(data.symbol)
        created = await self.db.hourly_bars.create(
            data={
                "symbol_id": symbol_row.symbol_id,
                "bar_time": _as_naive_utc(data.timestamp),
                "open_price": data.open_price,
                "high_price": data.high_price,
                "low_price": data.low_price,
                "close_price": data.close_price,
                "volume": data.volume,
                "minute_count": data.minute_count,
            }
        )
        return self._from_mysql(created, symbol=symbol_row.symbol_code)

    async def _create_mongo(self, data: BarCreate) -> BarResponse:
        created = await self.db.hourly_bars.create(
            data={
                "symbol": data.symbol,
                "timestamp": _as_aware_utc(data.timestamp),
                "open_price": data.open_price,
                "high_price": data.high_price,
                "low_price": data.low_price,
                "close_price": data.close_price,
                "volume": data.volume,
                "minute_count": data.minute_count,
                "created_at": datetime.now(timezone.utc),
            }
        )
        return self._from_mongo(created)

    async def _update_mysql(self, bar_id: str, data: BarUpdate) -> BarResponse:
        parsed = self._mysql_id(bar_id)
        await self._mysql_by_id(bar_id)
        update: dict[str, Any] = {}
        symbol_code: str | None = None
        if data.symbol is not None:
            symbol_row = await self._mysql_symbol(data.symbol)
            update["symbol_id"] = symbol_row.symbol_id
            symbol_code = symbol_row.symbol_code
        if data.timestamp is not None:
            update["bar_time"] = _as_naive_utc(data.timestamp)
        for field in ("open_price", "high_price", "low_price", "close_price", "volume", "minute_count"):
            value = getattr(data, field)
            if value is not None:
                update[field] = value
        updated = await self.db.hourly_bars.update(where={"bar_id": parsed}, data=update)
        if symbol_code is None:
            record = await self.db.hourly_bars.find_unique(
                where={"bar_id": parsed},
                include={"symbols": True},
            )
            return self._from_mysql(record)
        return self._from_mysql(updated, symbol=symbol_code)

    async def _update_mongo(self, bar_id: str, data: BarUpdate) -> BarResponse:
        await self._mongo_by_id(bar_id)
        update: dict[str, Any] = {}
        if data.symbol is not None:
            update["symbol"] = data.symbol
        if data.timestamp is not None:
            update["timestamp"] = _as_aware_utc(data.timestamp)
        for field in ("open_price", "high_price", "low_price", "close_price", "volume", "minute_count"):
            value = getattr(data, field)
            if value is not None:
                update[field] = value
        updated = await self.db.hourly_bars.update(where={"id": bar_id}, data=update)
        return self._from_mongo(updated)

    async def _mysql_symbol(self, symbol: str) -> Any:
        row = await self.db.symbols.find_unique(where={"symbol_code": symbol})
        if row is None:
            raise UnknownSymbol(symbol)
        return row

    async def _mysql_by_id(self, bar_id: str) -> Any:
        parsed = self._mysql_id(bar_id)
        record = await self.db.hourly_bars.find_unique(
            where={"bar_id": parsed},
            include={"symbols": True},
        )
        if record is None:
            raise BarNotFound(bar_id)
        return record

    async def _mongo_by_id(self, bar_id: str) -> Any:
        try:
            record = await self.db.hourly_bars.find_unique(where={"id": bar_id})
        except Exception as exc:
            raise BarNotFound(bar_id) from exc
        if record is None:
            raise BarNotFound(bar_id)
        return record

    @staticmethod
    def _mysql_id(bar_id: str) -> int:
        try:
            return int(bar_id)
        except ValueError as exc:
            raise BarNotFound(bar_id) from exc

    @staticmethod
    def _from_mysql(record: Any, symbol: str | None = None) -> BarResponse:
        if symbol is None:
            symbol = record.symbols.symbol_code
        return BarResponse(
            bar_id=int(record.bar_id),
            symbol=symbol,
            timestamp=record.bar_time,
            open_price=float(record.open_price),
            high_price=float(record.high_price),
            low_price=float(record.low_price),
            close_price=float(record.close_price),
            volume=float(record.volume),
            minute_count=int(record.minute_count),
        )

    @staticmethod
    def _from_mongo(record: Any) -> BarResponse:
        return BarResponse(
            bar_id=str(record.id),
            symbol=record.symbol,
            timestamp=record.timestamp,
            open_price=float(record.open_price),
            high_price=float(record.high_price),
            low_price=float(record.low_price),
            close_price=float(record.close_price),
            volume=float(record.volume),
            minute_count=int(record.minute_count),
        )
