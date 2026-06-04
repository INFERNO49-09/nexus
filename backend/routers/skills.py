"""
Skills router - list, execute, create, refine agent skills
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.skill_registry import skill_registry

logger = logging.getLogger(__name__)
router = APIRouter()


class ExecuteSkillRequest(BaseModel):
    skill_name: str
    params: dict = {}


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    code: str


@router.get("")
async def list_skills():
    return {"skills": skill_registry.list_skills()}


@router.get("/{skill_name}")
async def get_skill(skill_name: str):
    skill = skill_registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return skill


@router.post("/execute")
async def execute_skill(req: ExecuteSkillRequest):
    result = await skill_registry.execute(req.skill_name, **req.params)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("")
async def create_skill(req: CreateSkillRequest):
    result = await skill_registry.create_skill(req.name, req.description, req.code)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create skill"))
    return result


@router.post("/{skill_name}/refine")
async def refine_skill(skill_name: str):
    improved_code = await skill_registry.ai_refine_skill(skill_name)
    if not improved_code:
        raise HTTPException(status_code=404, detail="Skill not found or refinement failed")
    return {"skill": skill_name, "improved_code": improved_code}
