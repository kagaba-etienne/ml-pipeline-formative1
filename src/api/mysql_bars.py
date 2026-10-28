from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from src.database.clients import mysql_client
from src.schemas.bars import BarCreate, BarResponse, BarUpdate
from src.services.bar_service import BarNotFound, BarService, DuplicateBar, UnknownSymbol


router = APIRouter(prefix="/api/mysql/bars", tags=["MySQL bars"], redirect_slashes=False)


def get_service() -> BarService:
    return BarService(mysql_client, "mysql")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UnknownSymbol):
        return HTTPException(status_code=404, detail=f"Unknown symbol {exc.symbol}")
    if isinstance(exc, BarNotFound):
        return HTTPException(status_code=404, detail="Bar not found")
    if isinstance(exc, DuplicateBar):
        return HTTPException(status_code=409, detail="A bar already exists for that symbol and hour")
    raise exc


@router.get("/latest", response_model=BarResponse)
async def latest_bar(
    symbol: str = Query(min_length=1),
    service: BarService = Depends(get_service),
) -> BarResponse:
    try:
        return await service.latest_bar(symbol)
    except (UnknownSymbol, BarNotFound) as exc:
        raise _http_error(exc) from exc


@router.get("", response_model=list[BarResponse])
async def bars_in_range(
    symbol: str = Query(min_length=1),
    start: datetime = Query(),
    end: datetime = Query(),
    limit: int = Query(1000, ge=1, le=5000),
    service: BarService = Depends(get_service),
) -> list[BarResponse]:
    try:
        return await service.bars_in_range(symbol, start, end, limit)
    except UnknownSymbol as exc:
        raise _http_error(exc) from exc


@router.get("/{bar_id}", response_model=BarResponse)
async def get_bar(bar_id: str, service: BarService = Depends(get_service)) -> BarResponse:
    try:
        return await service.get_bar(bar_id)
    except BarNotFound as exc:
        raise _http_error(exc) from exc


@router.post("", response_model=BarResponse, status_code=201)
async def create_bar(
    data: BarCreate,
    service: BarService = Depends(get_service),
) -> BarResponse:
    try:
        return await service.create_bar(data)
    except (UnknownSymbol, DuplicateBar) as exc:
        raise _http_error(exc) from exc


@router.put("/{bar_id}", response_model=BarResponse)
async def update_bar(
    bar_id: str,
    data: BarUpdate,
    service: BarService = Depends(get_service),
) -> BarResponse:
    try:
        return await service.update_bar(bar_id, data)
    except (UnknownSymbol, BarNotFound, DuplicateBar) as exc:
        raise _http_error(exc) from exc


@router.delete("/{bar_id}", status_code=204)
async def delete_bar(bar_id: str, service: BarService = Depends(get_service)) -> None:
    try:
        await service.delete_bar(bar_id)
    except BarNotFound as exc:
        raise _http_error(exc) from exc
