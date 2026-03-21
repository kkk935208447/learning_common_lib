"""Deterministic mock LLM used by the deep-search demo."""

from __future__ import annotations

import hashlib
import json

try:
    from ...ports.llm_port import LLMPort, LLMResponse
except ImportError:
    from 最小可执行demo.ports.llm_port import LLMPort, LLMResponse


class MockLLM(LLMPort):
    model_name = "gpt-5.4-mock"

    async def generate(
        self,
        prompt,
        structured_schema=None,
        timeout_s: int | None = None,
    ) -> LLMResponse:
        normalized = self._normalize_prompt(prompt)
        lowered = normalized.lower()
        usage = {
            "prompt_tokens": max(1, len(normalized) // 4),
            "completion_tokens": 96,
            "timeout_s": timeout_s or 0,
        }
        structured_output = None
        text = self._build_text(normalized)

        if structured_schema is not None:
            structured_output = self._build_structured_output(prompt, normalized, lowered, structured_schema)

        return {
            "text": text,
            "structured_output": structured_output,
            "usage": usage,
            "model": self.model_name,
        }

    def _normalize_prompt(self, prompt) -> str:
        if isinstance(prompt, dict):
            if prompt.get("query"):
                return str(prompt["query"]).strip()
            if prompt.get("text"):
                return str(prompt["text"]).strip()
            return json.dumps(prompt, ensure_ascii=False, sort_keys=True)
        return str(prompt or "").strip()

    def _build_text(self, prompt: str) -> str:
        digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8]
        return f"[mock:{digest}] {prompt[:160] or 'empty prompt'}"

    def _build_structured_output(self, raw_prompt, prompt: str, lowered: str, structured_schema):
        kind = structured_schema
        if isinstance(raw_prompt, dict):
            kind = kind or raw_prompt.get("kind")

        if kind == "rewrite":
            query = raw_prompt.get("query", "") if isinstance(raw_prompt, dict) else prompt
            keywords = raw_prompt.get("keywords", []) if isinstance(raw_prompt, dict) else []
            rewritten = [str(query).strip()]
            if keywords:
                rewritten.append(f"{query} {' '.join(keywords[:2])}".strip())
            if "变化" in str(query) or "比较" in str(query):
                rewritten.append(f"{query} 最新 版本 差异".strip())
            return {"queries": list(dict.fromkeys([value for value in rewritten if value]))}

        if kind == "draft_answer":
            evidence = raw_prompt.get("evidence", []) if isinstance(raw_prompt, dict) else []
            lines = []
            citations = []
            for item in evidence[:3]:
                locator = item.get("card_uid") or item.get("chunk_uid") or "unknown"
                citations.append(locator)
                lines.append(f"- {item.get('claim') or item.get('snippet') or item.get('content', '')[:80]}")
            answer = "基于当前证据，整理结果如下：\n" + ("\n".join(lines) if lines else "- 当前暂无充足证据")
            return {"answer": answer, "citations": citations}

        if kind == "reasoning_summary":
            evidence = raw_prompt.get("evidence", []) if isinstance(raw_prompt, dict) else []
            query = raw_prompt.get("query", "") if isinstance(raw_prompt, dict) else prompt
            points = []
            citations = []
            for item in evidence[:4]:
                locator = item.get("card_uid") or item.get("chunk_uid") or "unknown"
                citations.append(locator)
                points.append(item.get("claim") or item.get("content", "")[:120])
            body = "\n".join(f"- {point}" for point in points) if points else "- 当前暂无充分证据"
            answer = (
                f"围绕问题“{query}”，综合已有证据形成结构化汇总：\n"
                "一、核心变化\n"
                f"{body}\n"
                "二、证据口径\n"
                f"- 当前汇总基于 {len(citations)} 条证据卡。"
            )
            return {"answer": answer, "citations": citations}

        if kind == "final_answer":
            findings = raw_prompt.get("findings", []) if isinstance(raw_prompt, dict) else []
            citations = raw_prompt.get("citations", []) if isinstance(raw_prompt, dict) else []
            uncovered = raw_prompt.get("uncovered", []) if isinstance(raw_prompt, dict) else []
            focus = raw_prompt.get("focus") if isinstance(raw_prompt, dict) else None
            body = "\n".join(f"- {item}" for item in findings) or "- 未产出稳定结论"
            if uncovered:
                body += "\n\n未覆盖信息点：\n" + "\n".join(f"- {item}" for item in uncovered)
            prefix = ""
            if focus == "opt_policy":
                prefix = "回答口径：制度解释优先\n"
            elif focus == "opt_change":
                prefix = "回答口径：变更摘要优先\n"
            return {"answer": f"{prefix}最终汇总如下：\n{body}", "citations": citations}

        if kind == "session_summary":
            turns = raw_prompt.get("turns", []) if isinstance(raw_prompt, dict) else []
            recent = [turn.get("content", "") for turn in turns[-3:]]
            return {"summary": " | ".join(value[:50] for value in recent if value)}

        if "clarify" in lowered or "澄清" in lowered:
            return {
                "question": "请选择你关心的时间范围",
                "question_type": "SINGLE_SELECT",
                "options": [
                    {"id": "opt_30d", "label": "近 30 天"},
                    {"id": "opt_90d", "label": "近 90 天"},
                ],
                "default_option_id": "opt_90d",
                "clarification_source": "PREPLAN",
            }
        if "verify" in lowered or "校验" in lowered:
            return {
                "factual_pass": True,
                "citation_pass": True,
                "sensitive_pass": True,
                "notes": "mock verification passed",
            }
        if "plan" in lowered or "规划" in lowered:
            return {
                "task_profile": {
                    "intent": "comparison" if "变化" in prompt else "lookup",
                    "complexity": "medium",
                    "risk": "low",
                },
                "plan_nodes": [
                    {
                        "subtask_code": "ST-001",
                        "task_type": "RETRIEVAL",
                        "description": "检索知识库中的核心事实",
                    }
                ],
            }
        if "final" in lowered or "汇总" in lowered or "总结" in lowered:
            return {
                "final_answer": self._build_text(prompt),
                "confidence": 0.82,
                "citations": [],
            }
        return {
            "answer": self._build_text(prompt),
            "confidence": 0.78,
        }
