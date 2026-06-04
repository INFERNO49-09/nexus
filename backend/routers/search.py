"""
Search router - web search and URL reading
"""
import logging
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel
from core.search_engine import search_engine
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class ReadUrlRequest(BaseModel):
    url: str
    max_chars: int = 8000


@router.get("")
async def web_search(q: str = Query(..., description="Search query"),
                     n: int = Query(8, le=20)):
    results = await search_engine.search(q, n=n)
    return {"query": q, "results": results, "count": len(results)}


@router.post("/read")
async def read_url(req: ReadUrlRequest):
    result = await search_engine.read_url(req.url, req.max_chars)
    return result
