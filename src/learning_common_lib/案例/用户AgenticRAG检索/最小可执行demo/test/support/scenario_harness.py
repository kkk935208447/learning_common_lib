"""Scenario-driven test adapters that can be injected into API/worker processes."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.language_models import FakeListLLM

try:
    from ...infrastructure.file_search_reader import FileSearchReader
    from ...infrastructure.file_vector_reader import FileVectorReader
    from ...infrastructure.mock.mock_llm import MockLLM
    from ...infrastructure.settings import get_settings
    from ...ports.llm_port import LLMPort, LLMResponse
    from ...ports.search_read_port import SearchReadPort
    from ...ports.vector_read_port import RetrievalHit, VectorReadPort
except ImportError:
    from 最小可执行demo.infrastructure.file_search_reader import FileSearchReader
    from 最小可执行demo.infrastructure.file_vector_reader import FileVectorReader
    from 最小可执行demo.infrastructure.mock.mock_llm import MockLLM
    from 最小可执行demo.infrastructure.settings import get_settings
    from 最小可执行demo.ports.llm_port import LLMPort, LLMResponse
    from 最小可执行demo.ports.search_read_port import SearchReadPort
    from 最小可执行demo.ports.vector_read_port import RetrievalHit, VectorReadPort


@dataclass(slots=True)
class ScenarioFixture:
    id: str
    llm_backend: str
    llm_script: dict[str, Any]
    retrieval_script: dict[str, Any]
    input: dict[str, Any]
    fault_injection: dict[str, Any]
    expected: dict[str, Any]


def load_active_scenario_id() -> str | None:
    settings = get_settings()
    if settings.test_scenario_id:
        return settings.test_scenario_id
    path = settings.test_results_dir / "active_scenario.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenario_id = str(payload.get("scenario_id") or "").strip()
    return scenario_id or None


def load_scenario_fixture(scenario_id: str) -> ScenarioFixture:
    settings = get_settings()
    path = settings.test_fixtures_dir / "scenarios" / f"{scenario_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ScenarioFixture(
        id=str(payload["id"]),
        llm_backend=str(payload.get("llm_backend") or "scripted"),
        llm_script=dict(payload.get("llm_script") or {}),
        retrieval_script=dict(payload.get("retrieval_script") or {}),
        input=dict(payload.get("input") or {}),
        fault_injection=dict(payload.get("fault_injection") or {}),
        expected=dict(payload.get("expected") or {}),
    )


def _normalize_llm_payload(payload: Any) -> LLMResponse:
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {
                "text": payload,
                "structured_output": None,
                "usage": {},
                "model": "scenario-fake-llm",
            }
        payload = parsed
    if not isinstance(payload, dict):
        return {
            "text": str(payload),
            "structured_output": None,
            "usage": {},
            "model": "scenario-fake-llm",
        }
    return {
        "text": str(payload.get("text") or ""),
        "structured_output": payload.get("structured_output"),
        "usage": dict(payload.get("usage") or {}),
        "model": str(payload.get("model") or "scenario-fake-llm"),
    }


class ScenarioLLMAdapter(LLMPort):
    def __init__(self, fixture: ScenarioFixture, *, fallback: LLMPort) -> None:
        self.fixture = fixture
        self.fallback = fallback
        responses = fixture.llm_script.get("responses") or {}
        self._scripted_queues = {
            key: deque(list(items))
            for key, items in responses.items()
        }
        self._langchain_models = {
            key: FakeListLLM(
                responses=[
                    item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                    for item in items
                ]
            )
            for key, items in responses.items()
        }

    @staticmethod
    def _kind_of(prompt: Any, structured_schema: Any | None) -> str:
        if structured_schema is not None:
            return str(structured_schema)
        if isinstance(prompt, dict) and prompt.get("kind"):
            return str(prompt["kind"])
        return "default"

    @staticmethod
    def _prompt_as_text(prompt: Any) -> str:
        if isinstance(prompt, str):
            return prompt
        return json.dumps(prompt, ensure_ascii=False, sort_keys=True)

    async def generate(
        self,
        prompt: str,
        structured_schema: Any | None = None,
        timeout_s: int | None = None,
    ) -> LLMResponse:
        kind = self._kind_of(prompt, structured_schema)
        if self.fixture.llm_backend == "langchain_fake":
            model = self._langchain_models.get(kind) or self._langchain_models.get("default")
            if model is not None:
                raw = await model.ainvoke(self._prompt_as_text(prompt))
                payload = _normalize_llm_payload(raw)
                payload["usage"] = {**payload.get("usage", {}), "timeout_s": timeout_s or 0}
                return payload
        queue = self._scripted_queues.get(kind) or self._scripted_queues.get("default")
        if queue:
            payload = _normalize_llm_payload(queue.popleft())
            payload["usage"] = {**payload.get("usage", {}), "timeout_s": timeout_s or 0}
            return payload
        return await self.fallback.generate(prompt, structured_schema=structured_schema, timeout_s=timeout_s)


class _ScenarioRuleReader:
    def __init__(self, script: dict[str, Any], *, fallback: Any) -> None:
        self.fallback = fallback
        self.sequence = deque(list(script.get("sequence") or []))
        self.rules = [dict(item) for item in list(script.get("rules") or [])]

    @staticmethod
    def _matches(rule: dict[str, Any], query: str) -> bool:
        needle = str(rule.get("match") or "")
        if not needle:
            return True
        return needle in query

    @staticmethod
    def _coerce_hits(raw_hits: list[dict[str, Any]], *, top_k: int) -> list[RetrievalHit]:
        hits = [dict(item) for item in raw_hits]
        hits.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return hits[:top_k]

    def _consume_sequence(self, query: str, top_k: int) -> list[RetrievalHit] | None:
        if not self.sequence:
            return None
        rule = dict(self.sequence[0])
        if not self._matches(rule, query):
            return None
        if rule.get("consume", True):
            self.sequence.popleft()
        return self._coerce_hits(list(rule.get("hits") or []), top_k=top_k)

    def _consume_rule(self, query: str, top_k: int) -> list[RetrievalHit] | None:
        for rule in self.rules:
            if rule.get("_consumed") and rule.get("consume", True):
                continue
            if not self._matches(rule, query):
                continue
            if rule.get("consume", True):
                rule["_consumed"] = True
            return self._coerce_hits(list(rule.get("hits") or []), top_k=top_k)
        return None


class ScenarioVectorReader(VectorReadPort):
    def __init__(self, fixture: ScenarioFixture, *, fallback: VectorReadPort) -> None:
        self.reader = _ScenarioRuleReader(
            dict((fixture.retrieval_script or {}).get("vector") or {}),
            fallback=fallback,
        )

    async def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalHit]:
        sequence_hits = self.reader._consume_sequence(query, top_k)
        if sequence_hits is not None:
            return sequence_hits
        rule_hits = self.reader._consume_rule(query, top_k)
        if rule_hits is not None:
            return rule_hits
        return await self.reader.fallback.search(query, top_k=top_k, filters=filters)


class ScenarioSearchReader(SearchReadPort):
    def __init__(self, fixture: ScenarioFixture, *, fallback: SearchReadPort) -> None:
        self.reader = _ScenarioRuleReader(
            dict((fixture.retrieval_script or {}).get("search") or {}),
            fallback=fallback,
        )

    async def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalHit]:
        sequence_hits = self.reader._consume_sequence(query, top_k)
        if sequence_hits is not None:
            return sequence_hits
        rule_hits = self.reader._consume_rule(query, top_k)
        if rule_hits is not None:
            return rule_hits
        return await self.reader.fallback.search(query, top_k=top_k, filters=filters)


@dataclass(slots=True)
class ScenarioHarness:
    fixture: ScenarioFixture

    def build_llm(self) -> ScenarioLLMAdapter:
        return ScenarioLLMAdapter(self.fixture, fallback=MockLLM())

    def build_vector_reader(self) -> ScenarioVectorReader:
        return ScenarioVectorReader(self.fixture, fallback=FileVectorReader())

    def build_search_reader(self) -> ScenarioSearchReader:
        return ScenarioSearchReader(self.fixture, fallback=FileSearchReader())


def build_scenario_harness() -> ScenarioHarness:
    scenario_id = load_active_scenario_id()
    if not scenario_id:
        raise ValueError("active test scenario 未设置")
    return ScenarioHarness(load_scenario_fixture(scenario_id))
