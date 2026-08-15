from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Item(BaseModel):
    id: int
    name: str


app = FastAPI(title="Sample Inventory API", version="1.0.0")
items: dict[int, Item] = {
    1: Item(id=1, name="Starter item"),
    2: Item(id=2, name="Boundary item"),
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/items/{item_id}", response_model=dict[str, object])
def get_item(item_id: int) -> dict[str, object]:
    item = items.get(item_id)
    if item is None:
        return {"success": False, "errorMsg": "item not found", "data": None}
    return {"success": True, "errorMsg": None, "data": item.model_dump()}


@app.post("/items", status_code=201, response_model=dict[str, object])
def create_item(payload: ItemCreate) -> dict[str, object]:
    next_id = max(items) + 1 if items else 1
    item = Item(id=next_id, name=payload.name)
    items[next_id] = item
    return {"success": True, "errorMsg": None, "data": item.model_dump()}

