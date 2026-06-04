"""
Agent engine - autonomous multi-step task execution with tool use and planning
Uses ReAct (Reasoning + Acting) loop: Think  Act  Observe  Repeat
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import AsyncGenerator, Optional

from core.config import settings
from core.ollama_client import ollama
from core.skill_registry import skill_registry

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """You are Nexus, an autonomous AI agent. You solve tasks step by step using tools.

Available tools:
- web_search(query, n=8) - search the web
- read_url(url) - read full content of a URL
- memory_search(query) - search your persistent memory
- memory_save(text, type) - save something to memory (types: fact, pref, ctx, skill)
- code_exec(code) - run Python code
- summarize(text) - summarize long text

To use a tool, respond EXACTLY in this format:
THOUGHT: <your reasoning>
ACTION: <tool_name>
PARAMS: <json params object>

When you have a final answer, respond:
THOUGHT: <final reasoning>
FINAL: <your complete answer>

Rules:
- Always think before acting
- Use tools when you need real information
- Be thorough but efficient
- Save important findings to memory"""


class AgentStep:
    def __init__(self, step_num: int, thought: str = "", action: str = "",
                 params: dict = None, observation: str = "", is_final: bool = False):
        self.step_num = step_num
        self.thought = thought
        self.action = action
        self.params = params or {}
        self.observation = observation
        self.is_final = is_final
        self.timestamp = datetime.utcnow().isoformat()
        self.elapsed_s = 0.0

    def to_dict(self) -> dict:
        return {
            "step": self.step_num,
            "thought": self.thought,
            "action": self.action,
            "params": self.params,
            "observation": self.observation,
            "is_final": self.is_final,
            "timestamp": self.timestamp,
            "elapsed_s": self.elapsed_s,
        }


class AgentRun:
    def __init__(self, run_id: str, task: str, model: str):
        self.run_id = run_id
        self.task = task
        self.model = model
        self.steps: list[AgentStep] = []
        self.final_answer: str = ""
        self.status: str = "running"  # running | done | failed | cancelled
        self.created_at = datetime.utcnow().isoformat()
        self.finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "model": self.model,
            "steps": [s.to_dict() for s in self.steps],
            "final_answer": self.final_answer,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class AgentEngine:
    def __init__(self):
        self._runs: dict[str, AgentRun] = {}
        self._cancel_flags: dict[str, bool] = {}

    def get_run(self, run_id: str) -> Optional[AgentRun]:
        return self._runs.get(run_id)

    def list_runs(self) -> list[dict]:
        return [r.to_dict() for r in self._runs.values()]

    def cancel(self, run_id: str):
        self._cancel_flags[run_id] = True

    async def run(
        self,
        task: str,
        model: str = None,
        system_context: str = "",
        max_steps: int = None,
    ) -> AsyncGenerator[dict, None]:
        """Run agent task, yielding step events as they happen."""
        run_id = str(uuid.uuid4())
        model = model or settings.DEFAULT_MODEL
        max_steps = max_steps or settings.MAX_AGENT_STEPS

        run = AgentRun(run_id=run_id, task=task, model=model)
        self._runs[run_id] = run
        self._cancel_flags[run_id] = False

        yield {"event": "start", "run_id": run_id, "task": task}

        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT + (f"\n\nContext:\n{system_context}" if system_context else "")},
            {"role": "user", "content": f"Task: {task}"},
        ]

        try:
            for step_num in range(1, max_steps + 1):
                if self._cancel_flags.get(run_id):
                    run.status = "cancelled"
                    yield {"event": "cancelled", "run_id": run_id}
                    return

                start = time.time()
                # Get LLM decision
                try:
                    response = await ollama.chat(
                        messages=messages,
                        model=model,
                        temperature=0.3,
                        max_tokens=1024,
                        stream=False,
                    )
                    llm_text = response["content"]
                except Exception as e:
                    run.status = "failed"
                    yield {"event": "error", "error": str(e)}
                    return

                # Parse the response
                step = self._parse_response(step_num, llm_text)
                step.elapsed_s = round(time.time() - start, 2)

                messages.append({"role": "assistant", "content": llm_text})

                if step.is_final:
                    run.final_answer = step.thought
                    run.status = "done"
                    run.finished_at = datetime.utcnow().isoformat()
                    run.steps.append(step)
                    yield {"event": "step", "run_id": run_id, "step": step.to_dict()}
                    yield {"event": "done", "run_id": run_id, "answer": run.final_answer}
                    return

                # Execute the tool
                if step.action:
                    obs = await self._execute_tool(step.action, step.params)
                    step.observation = obs
                    # Feed observation back
                    messages.append({
                        "role": "user",
                        "content": f"OBSERVATION: {obs[:3000]}"
                    })

                run.steps.append(step)
                yield {"event": "step", "run_id": run_id, "step": step.to_dict()}

                # Small delay to prevent hammering
                await asyncio.sleep(0.1)

            # Max steps reached
            run.status = "done"
            run.final_answer = "Reached maximum steps. Here is what I found so far: " + \
                "\n".join([s.observation for s in run.steps if s.observation][-3:])
            run.finished_at = datetime.utcnow().isoformat()
            yield {"event": "done", "run_id": run_id, "answer": run.final_answer}

        except Exception as e:
            logger.exception("Agent run %s failed", run_id)
            run.status = "failed"
            run.finished_at = datetime.utcnow().isoformat()
            yield {"event": "error", "run_id": run_id, "error": str(e)}

    def _parse_response(self, step_num: int, text: str) -> AgentStep:
        step = AgentStep(step_num=step_num)
        lines = text.strip().split("\n")

        # Check for FINAL answer
        for i, line in enumerate(lines):
            if line.startswith("FINAL:"):
                step.thought = self._extract_after(text, "THOUGHT:")
                step.is_final = True
                step.action = "final_answer"
                remaining = "\n".join(lines[i:])
                step.observation = remaining.replace("FINAL:", "").strip()
                return step

        step.thought = self._extract_after(text, "THOUGHT:")
        action_raw = self._extract_after(text, "ACTION:")
        params_raw = self._extract_after(text, "PARAMS:")

        if action_raw:
            step.action = action_raw.strip().split()[0].lower()
        if params_raw:
            try:
                step.params = json.loads(params_raw.strip())
            except json.JSONDecodeError:
                step.params = {}

        if not step.action:
            # No structured action - treat as final
            step.is_final = True
            step.observation = text

        return step

    def _extract_after(self, text: str, prefix: str) -> str:
        idx = text.find(prefix)
        if idx == -1:
            return ""
        after = text[idx + len(prefix):]
        # Take until next keyword
        for kw in ["THOUGHT:", "ACTION:", "PARAMS:", "OBSERVATION:", "FINAL:"]:
            end = after.find(kw)
            if end != -1:
                after = after[:end]
        return after.strip()

    async def _execute_tool(self, tool_name: str, params: dict) -> str:
        """Execute a skill and return formatted observation."""
        try:
            result = await skill_registry.execute(tool_name, **params)
            if "error" in result:
                return f"Error: {result['error']}"
            data = result.get("result", result)
            if isinstance(data, list):
                # Format search results
                lines = []
                for i, r in enumerate(data[:6], 1):
                    if isinstance(r, dict):
                        lines.append(f"{i}. {r.get('title','')}\n   URL: {r.get('url','')}\n   {r.get('snippet','')[:200]}")
                    else:
                        lines.append(str(r)[:300])
                return "\n\n".join(lines)
            if isinstance(data, dict):
                return json.dumps(data, indent=2)[:2000]
            return str(data)[:2000]
        except Exception as e:
            return f"Tool execution failed: {e}"


agent_engine = AgentEngine()
