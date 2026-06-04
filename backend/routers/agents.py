"""
Agents router - run autonomous agents with SSE streaming step events
"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from core.agent_engine import agent_engine
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class AgentRunRequest(BaseModel):
    task: str
    model: Optional[str] = None
    system_context: Optional[str] = ""
    max_steps: Optional[int] = None


@router.post("/run")
async def run_agent(req: AgentRunRequest):
    """Stream agent execution steps via SSE."""
    async def stream():
        async for event in agent_engine.run(
            task=req.task,
            model=req.model or settings.DEFAULT_MODEL,
            system_context=req.system_context or "",
            max_steps=req.max_steps,
        ):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/runs")
async def list_runs():
    return {"runs": agent_engine.list_runs()}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = agent_engine.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    agent_engine.cancel(run_id)
    return {"cancelled": True, "run_id": run_id}
