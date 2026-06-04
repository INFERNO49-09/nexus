"""
Memory router - add, search, list, delete memory entries
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from core.memory_store import memory_store

logger = logging.getLogger(__name__)
router = APIRouter()


class MemoryAddRequest(BaseModel):
    text: str
    memory_type: str = "ctx"
    source: str = "manual"


class MemorySearchRequest(BaseModel):
    query: str
    n: int = 5
    memory_type: Optional[str] = None


@router.get("")
async def list_memories(limit: int = Query(100, le=500), offset: int = 0):
    entries = await memory_store.list_all(limit=limit, offset=offset)
    return {"entries": entries, "count": len(entries)}


@router.post("/search")
async def search_memory(req: MemorySearchRequest):
    results = await memory_store.search(req.query, n_results=req.n, memory_type=req.memory_type)
    return {"results": results, "count": len(results)}


@router.post("")
async def add_memory(req: MemoryAddRequest):
    entry_id = await memory_store.add(
        text=req.text, memory_type=req.memory_type, source=req.source
    )
    if not entry_id:
        raise HTTPException(status_code=503, detail="Memory store unavailable")
    return {"id": entry_id, "saved": True}


@router.get("/stats")
async def memory_stats():
    return await memory_store.stats()


@router.delete("/{entry_id}")
async def delete_memory(entry_id: str):
    success = await memory_store.delete(entry_id)
    return {"deleted": success}
