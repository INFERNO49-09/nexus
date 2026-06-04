"""
Research router - multi-step web research with SSE streaming progress
"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from core.research_engine import research_engine
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class ResearchRequest(BaseModel):
    question: str
    depth: Optional[int] = None
    model: Optional[str] = None


@router.post("/run")
async def run_research(req: ResearchRequest):
    """Stream research progress events via SSE."""
    async def stream():
        async for event in research_engine.run(
            question=req.question,
            depth=req.depth or settings.DEFAULT_RESEARCH_DEPTH,
            model=req.model,
        ):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/reports")
async def list_reports():
    return {"reports": research_engine.list_reports()}


@router.get("/reports/{run_id}")
async def get_report(run_id: str):
    report = research_engine.get_report(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
