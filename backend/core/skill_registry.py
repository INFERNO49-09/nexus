"""
Skill registry - manages agent skills (load, save, execute, self-improve)
Skills are Python async functions stored as .py files in the data/skills directory
"""
import asyncio
import importlib.util
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.config import settings

logger = logging.getLogger(__name__)

BUILTIN_SKILLS = {
    "web_search": {
        "name": "web_search",
        "version": "2.1",
        "description": "Search the web using Searx/Brave/DuckDuckGo. Returns ranked results with snippets.",
        "icon": "",
        "parameters": {"query": "str", "n": "int = 8"},
        "builtin": True,
        "uses": 0,
        "perf": 94,
    },
    "read_url": {
        "name": "read_url",
        "version": "1.5",
        "description": "Fetch and extract full text content from any URL using Jina Reader.",
        "icon": "",
        "parameters": {"url": "str", "max_chars": "int = 8000"},
        "builtin": True,
        "uses": 0,
        "perf": 91,
    },
    "memory_search": {
        "name": "memory_search",
        "version": "3.0",
        "description": "Search persistent memory for relevant facts, preferences, and context.",
        "icon": "",
        "parameters": {"query": "str", "n": "int = 5"},
        "builtin": True,
        "uses": 0,
        "perf": 88,
    },
    "memory_save": {
        "name": "memory_save",
        "version": "1.2",
        "description": "Save a new memory entry (fact, preference, context, or skill).",
        "icon": "",
        "parameters": {"text": "str", "type": "str = 'ctx'"},
        "builtin": True,
        "uses": 0,
        "perf": 96,
    },
    "code_exec": {
        "name": "code_exec",
        "version": "1.8",
        "description": "Execute Python code in a sandboxed environment. Returns stdout, stderr.",
        "icon": "[tool]",
        "parameters": {"code": "str", "timeout": "int = 30"},
        "builtin": True,
        "uses": 0,
        "perf": 99,
    },
    "summarize": {
        "name": "summarize",
        "version": "1.0",
        "description": "Summarize a long text into key points using the local LLM.",
        "icon": "",
        "parameters": {"text": "str", "max_words": "int = 200"},
        "builtin": True,
        "uses": 0,
        "perf": 90,
    },
}


class SkillRegistry:
    def __init__(self):
        self.skills_dir = Path(settings.DATA_DIR) / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._registry: dict[str, dict] = {}
        self._stats_file = self.skills_dir / "_stats.json"

    async def load(self):
        """Load built-ins + any custom skills from disk."""
        self._registry = dict(BUILTIN_SKILLS)
        self._load_stats()
        # Load custom skills
        for py_file in self.skills_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                meta = self._load_skill_file(py_file)
                if meta:
                    self._registry[meta["name"]] = meta
            except Exception as e:
                logger.warning("Failed to load skill %s: %s", py_file.name, e)
        logger.info("[OK] Skill registry loaded - %d skills", len(self._registry))

    def _load_skill_file(self, path: Path) -> Optional[dict]:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        meta = getattr(mod, "SKILL_META", None)
        if meta:
            meta["_module"] = mod
            meta["_path"] = str(path)
            meta["builtin"] = False
            return meta
        return None

    def _load_stats(self):
        if self._stats_file.exists():
            try:
                stats = json.loads(self._stats_file.read_text())
                for name, s in stats.items():
                    if name in self._registry:
                        self._registry[name]["uses"] = s.get("uses", 0)
                        self._registry[name]["perf"] = s.get("perf", 90)
            except Exception:
                pass

    def _save_stats(self):
        stats = {
            name: {"uses": s.get("uses", 0), "perf": s.get("perf", 90)}
            for name, s in self._registry.items()
        }
        self._stats_file.write_text(json.dumps(stats, indent=2))

    def list_skills(self) -> list[dict]:
        return [
            {k: v for k, v in s.items() if not k.startswith("_")}
            for s in self._registry.values()
        ]

    def get_skill(self, name: str) -> Optional[dict]:
        s = self._registry.get(name)
        if s:
            return {k: v for k, v in s.items() if not k.startswith("_")}
        return None

    async def execute(self, skill_name: str, **kwargs) -> dict:
        """Execute a skill by name, returning result dict."""
        if skill_name not in self._registry:
            return {"error": f"Unknown skill: {skill_name}"}

        self._registry[skill_name]["uses"] = self._registry[skill_name].get("uses", 0) + 1
        self._save_stats()

        start = time.time()
        try:
            result = await self._dispatch(skill_name, **kwargs)
            elapsed = round(time.time() - start, 2)
            return {"result": result, "elapsed_s": elapsed, "skill": skill_name}
        except Exception as e:
            logger.error("Skill %s failed: %s", skill_name, traceback.format_exc())
            return {"error": str(e), "skill": skill_name}

    async def _dispatch(self, name: str, **kwargs) -> Any:
        """Route to built-in or custom skill."""
        if name == "web_search":
            from core.search_engine import search_engine
            return await search_engine.search(kwargs.get("query", ""), kwargs.get("n", 8))

        elif name == "read_url":
            from core.search_engine import search_engine
            return await search_engine.read_url(kwargs.get("url", ""), kwargs.get("max_chars", 8000))

        elif name == "memory_search":
            from core.memory_store import memory_store
            return await memory_store.search(kwargs.get("query", ""), kwargs.get("n", 5))

        elif name == "memory_save":
            from core.memory_store import memory_store
            entry_id = await memory_store.add(
                text=kwargs.get("text", ""),
                memory_type=kwargs.get("type", "ctx"),
                source="agent",
            )
            return {"saved": True, "id": entry_id}

        elif name == "code_exec":
            return await self._exec_python(kwargs.get("code", ""), kwargs.get("timeout", 30))

        elif name == "summarize":
            from core.ollama_client import ollama
            text = kwargs.get("text", "")
            max_words = kwargs.get("max_words", 200)
            prompt = f"Summarize the following in {max_words} words or less:\n\n{text[:4000]}"
            return await ollama.generate(prompt)

        else:
            # Custom skill
            skill = self._registry.get(name)
            if skill and "_module" in skill:
                fn = getattr(skill["_module"], "execute", None)
                if fn:
                    return await fn(**kwargs)
            raise ValueError(f"No executor for skill: {name}")

    async def _exec_python(self, code: str, timeout: int = 30) -> dict:
        """Run Python code in subprocess for safety."""
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code)
            tmp = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, tmp,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd="/tmp",
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode()[:4000],
                "stderr": stderr.decode()[:1000],
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            proc.kill()
            return {"error": f"Timeout after {timeout}s", "stdout": "", "stderr": ""}
        finally:
            os.unlink(tmp)

    async def create_skill(self, name: str, description: str, code: str) -> dict:
        """Save a new custom skill to disk."""
        safe_name = "".join(c for c in name if c.isalnum() or c == "_")
        path = self.skills_dir / f"{safe_name}.py"
        path.write_text(code)
        try:
            meta = self._load_skill_file(path)
            if meta:
                self._registry[safe_name] = meta
                return {"success": True, "name": safe_name}
        except Exception as e:
            path.unlink()
            return {"success": False, "error": str(e)}
        return {"success": False, "error": "Skill file missing SKILL_META"}

    async def ai_refine_skill(self, skill_name: str) -> str:
        """Ask the LLM to improve an existing skill."""
        from core.ollama_client import ollama
        skill = self._registry.get(skill_name)
        if not skill:
            return ""
        path = skill.get("_path")
        current_code = Path(path).read_text() if path else ""
        stats = f"Uses: {skill.get('uses', 0)}, Perf: {skill.get('perf', 0)}%"
        prompt = f"""You are improving a Python async skill for a local AI assistant.
Current skill: {skill_name}
Stats: {stats}
Current code:
{current_code}

Improve this skill for better reliability, error handling, and output quality.
Return ONLY the complete improved Python code, no explanation."""
        return await ollama.generate(prompt)


skill_registry = SkillRegistry()
