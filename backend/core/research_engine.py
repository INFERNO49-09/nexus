"""
Research engine - multi-step: plan  search  read sources  synthesize  report
Streams progress events so the frontend can show live updates
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

from core.config import settings
from core.ollama_client import ollama
from core.search_engine import search_engine

logger = logging.getLogger(__name__)


RESEARCH_SYSTEM = """You are a thorough research assistant. You gather information from multiple sources,
critically analyze it, and synthesize it into clear, well-structured reports.
Always cite your sources. Be factual, balanced, and comprehensive."""


class ResearchEngine:
    def __init__(self):
        self._runs: dict[str, dict] = {}
        self.reports_dir = Path(settings.DATA_DIR) / "research"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        question: str,
        depth: int = None,
        model: str = None,
    ) -> AsyncGenerator[dict, None]:
        """Run a full research cycle, yielding progress events."""
        depth = depth or settings.DEFAULT_RESEARCH_DEPTH
        model = model or settings.DEFAULT_MODEL
        run_id = str(uuid.uuid4())

        yield {"event": "start", "run_id": run_id, "question": question}

        # -- Phase 1: Planning ------------------------------------------------
        yield {"event": "progress", "phase": "planning", "message": "Planning research strategy"}

        queries = await self._plan_queries(question, depth, model)
        yield {"event": "progress", "phase": "planning",
               "message": f"Generated {len(queries)} search queries", "queries": queries}

        # -- Phase 2: Searching ------------------------------------------------
        yield {"event": "progress", "phase": "searching", "message": "Searching the web"}

        all_results = []
        for q in queries[:min(len(queries), 5)]:
            yield {"event": "progress", "phase": "searching", "message": f'Searching: "{q}"'}
            results = await search_engine.search(q, n=depth // max(len(queries), 1) + 2)
            all_results.extend(results)
            await asyncio.sleep(0.2)

        # Deduplicate by URL
        seen = set()
        unique_results = []
        for r in all_results:
            if r["url"] not in seen:
                seen.add(r["url"])
                unique_results.append(r)

        target_sources = min(depth, len(unique_results))
        yield {"event": "progress", "phase": "searching",
               "message": f"Found {len(unique_results)} unique sources, reading top {target_sources}"}

        # -- Phase 3: Reading -------------------------------------------------
        yield {"event": "progress", "phase": "reading", "message": "Reading sources"}

        sources_content = []
        read_tasks = [
            self._read_source(r, i + 1)
            for i, r in enumerate(unique_results[:target_sources])
        ]
        for coro in asyncio.as_completed(read_tasks):
            source = await coro
            if source["content"]:
                sources_content.append(source)
                yield {
                    "event": "progress",
                    "phase": "reading",
                    "message": f"Read: {source['title'][:60]} ({source['chars']} chars)",
                    "source": {"title": source["title"], "url": source["url"]},
                }

        yield {"event": "progress", "phase": "reading",
               "message": f"Successfully read {len(sources_content)} sources"}

        # -- Phase 4: Synthesis -----------------------------------------------
        yield {"event": "progress", "phase": "synthesizing",
               "message": f"Synthesizing {len(sources_content)} sources"}

        # Summarize each source first (saves context window)
        summaries = await self._summarize_sources(sources_content, question, model)
        yield {"event": "progress", "phase": "synthesizing",
               "message": "Source summaries complete, writing report"}

        # -- Phase 5: Writing -------------------------------------------------
        yield {"event": "progress", "phase": "writing", "message": "Writing final report"}

        report = await self._write_report(question, summaries, sources_content, model)

        # Save report
        report_path = self.reports_dir / f"{run_id}.json"
        report_data = {
            "run_id": run_id,
            "question": question,
            "report": report,
            "sources": [{"title": s["title"], "url": s["url"]} for s in sources_content],
            "created_at": datetime.utcnow().isoformat(),
            "model": model,
            "depth": depth,
        }
        report_path.write_text(json.dumps(report_data, indent=2))
        self._runs[run_id] = report_data

        yield {
            "event": "done",
            "run_id": run_id,
            "report": report,
            "sources": report_data["sources"],
            "source_count": len(sources_content),
        }

    async def _plan_queries(self, question: str, depth: int, model: str) -> list[str]:
        """Use LLM to generate diverse search queries for the topic."""
        n_queries = min(5, max(2, depth // 5))
        prompt = f"""Generate {n_queries} diverse search queries to thoroughly research this topic:
"{question}"

Return a JSON array of query strings only, no explanation. Example: ["query 1", "query 2"]
Queries should cover different aspects and use different keywords."""
        try:
            response = await ollama.generate(prompt, model=model)
            text = response.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                queries = json.loads(text[start:end])
                return [q for q in queries if isinstance(q, str)][:n_queries]
        except Exception as e:
            logger.debug("Query planning failed: %s", e)
        return [question]

    async def _read_source(self, result: dict, idx: int) -> dict:
        """Read a single source URL with timeout."""
        try:
            content_data = await asyncio.wait_for(
                search_engine.read_url(result["url"]),
                timeout=15,
            )
            return {
                "idx": idx,
                "title": result.get("title", result["url"]),
                "url": result["url"],
                "snippet": result.get("snippet", ""),
                "content": content_data.get("content", result.get("snippet", "")),
                "chars": content_data.get("chars", 0),
            }
        except Exception:
            return {
                "idx": idx,
                "title": result.get("title", result["url"]),
                "url": result["url"],
                "snippet": result.get("snippet", ""),
                "content": result.get("snippet", ""),
                "chars": len(result.get("snippet", "")),
            }

    async def _summarize_sources(
        self, sources: list[dict], question: str, model: str
    ) -> list[dict]:
        """Summarize each source in relation to the research question."""
        summaries = []
        for s in sources:
            content = s["content"][:3000]
            if not content.strip():
                continue
            prompt = f"""Summarize the key information from this source relevant to: "{question}"

Source: {s['title']}
Content: {content}

Write a concise summary (max 150 words) focusing only on relevant information:"""
            try:
                summary = await ollama.generate(prompt, model=model)
                summaries.append({
                    "idx": s["idx"],
                    "title": s["title"],
                    "url": s["url"],
                    "summary": summary.strip(),
                })
            except Exception:
                summaries.append({
                    "idx": s["idx"],
                    "title": s["title"],
                    "url": s["url"],
                    "summary": s["snippet"],
                })
        return summaries

    async def _write_report(
        self, question: str, summaries: list[dict], sources: list[dict], model: str
    ) -> str:
        """Write the final synthesized report."""
        sources_block = "\n\n".join([
            f"[{s['idx']}] {s['title']}\nURL: {s['url']}\n{s['summary']}"
            for s in summaries
        ])
        prompt = f"""{RESEARCH_SYSTEM}

Research question: {question}

Source summaries:
{sources_block}

Write a comprehensive, well-structured research report in Markdown format.
Include:
- Executive summary (2-3 sentences)
- Key findings (with inline citations like [1], [2])
- Detailed analysis organized by theme
- Conclusions and recommendations
- References section listing all sources

Be thorough, accurate, and cite sources inline throughout the report."""
        try:
            report = await ollama.chat(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                temperature=0.4,
                max_tokens=3000,
                stream=False,
            )
            return report["content"]
        except Exception as e:
            return f"# Research Report\n\n**Error generating report:** {e}\n\n## Sources\n" + \
                   "\n".join([f"- [{s['title']}]({s['url']})" for s in sources])

    def get_report(self, run_id: str) -> Optional[dict]:
        # Try in-memory first
        if run_id in self._runs:
            return self._runs[run_id]
        # Try disk
        path = self.reports_dir / f"{run_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def list_reports(self) -> list[dict]:
        reports = []
        for f in sorted(self.reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text())
                reports.append({
                    "run_id": data["run_id"],
                    "question": data["question"],
                    "source_count": len(data.get("sources", [])),
                    "created_at": data.get("created_at", ""),
                })
            except Exception:
                pass
        return reports[:50]


research_engine = ResearchEngine()
