#!/usr/bin/env python3
"""
===============================================================================
LLM-as-Judge RAG Evaluation (Phase 4, hardening plan)
===============================================================================
Q7 in the hardening plan: `rag_triad_evaluator.py`'s faithfulness metric is
substring-based -- an empty response scores a perfect 1.0 (nothing to
disprove), and any digit or ALL_CAPS token appearing anywhere in the context
counts a response fact as "grounded" regardless of actual meaning. That
scorer still exists (unchanged) as a zero-dependency fallback; this module
adds a real semantic judge using the local Ollama model already required by
`scripts/ollama_agentic_tool_runner.py` (`gemma4:latest`, confirmed present
via `ollama list`), scoring the same three RAG Triad dimensions
(context relevance, faithfulness, answer relevance) via natural-language
judgment instead of token overlap.

Fails open, not closed: if Ollama is unreachable, the model isn't pulled, or
the response can't be parsed as the expected JSON, `evaluate_triad` returns
None rather than raising -- callers are expected to fall back to
RAGTriadEvaluator's substring scorer (see evaluate_agentic_retrieval.py).
Evaluation tooling degrading gracefully when an optional local model is
absent follows the same shape as `_embedding_backend.py`'s
ALLOW_DEGRADED_EMBEDDINGS pattern, deliberately inverted: a security-relevant
retrieval path fails *closed* by default (never silently paper over missing
real embeddings), but an evaluation *harness* whose job is to grade a
benchmark should not abort the whole run over one optional scorer being
unavailable -- fail open here, matching `scripts/_otel_tracing.py`'s stated
reasoning for the same choice in that other non-critical-path module.

One live-verified caveat: even the LLM judge itself does not reliably self-
correct on the empty-response degenerate case that Q7 named -- asked to
grade an empty GENERATED RESPONSE with an explicit instruction to score it
0, gemma4:latest hallucinated a grounded-sounding justification and returned
1.0 anyway. Fixed with a deterministic code-level short-circuit below rather
than trusting the prompt to handle it -- the same "verify empirically, don't
assume" lesson this whole hardening pass has run on, applied to the judge
model itself.
===============================================================================
"""

import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger("LLMJudgeEvaluator")

OLLAMA_CHAT_URL = os.getenv("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_TAGS_URL = os.getenv("OLLAMA_TAGS_URL", "http://127.0.0.1:11434/api/tags")
LLM_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL", "gemma4:latest")
# Cold model load was observed live at ~6.3s; 30s leaves real headroom for a
# larger model or a loaded host without falsely timing out.
LLM_JUDGE_TIMEOUT_SECONDS = float(os.getenv("LLM_JUDGE_TIMEOUT_SECONDS", "30"))

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict, impartial evaluator of Retrieval-Augmented Generation "
    "(RAG) quality. You will be given a QUESTION, RETRIEVED CONTEXT, and a "
    "GENERATED RESPONSE. Score three dimensions, each a float from 0.0 (worst) "
    "to 1.0 (best):\n"
    "- context_relevance: how relevant the RETRIEVED CONTEXT is to answering the QUESTION.\n"
    "- faithfulness: whether every factual claim in the GENERATED RESPONSE is "
    "actually supported by the RETRIEVED CONTEXT (not outside knowledge, not "
    "invented). A response with an unsupported or fabricated claim must score low.\n"
    "- answer_relevance: how directly the GENERATED RESPONSE addresses the QUESTION asked.\n"
    "Respond with ONLY a single JSON object, no markdown code fences, no prose "
    "before or after, matching exactly this schema: "
    '{"context_relevance": <float>, "faithfulness": <float>, '
    '"answer_relevance": <float>, "rationale": "<one sentence>"}'
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _clamp01(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


class LLMJudgeEvaluator:
    """Real semantic RAG-Triad scoring via a local Ollama model. See module
    docstring for the fail-open contract and the empty-response caveat."""

    def __init__(self, model: Optional[str] = None, chat_url: Optional[str] = None,
                 tags_url: Optional[str] = None, timeout: Optional[float] = None):
        self.model = model or LLM_JUDGE_MODEL
        self.chat_url = chat_url or OLLAMA_CHAT_URL
        self.tags_url = tags_url or OLLAMA_TAGS_URL
        self.timeout = timeout if timeout is not None else LLM_JUDGE_TIMEOUT_SECONDS

    def is_available(self) -> bool:
        """Quick reachability + model-presence check against Ollama's own
        /api/tags -- lets a caller decide whether to attempt the (slower)
        judge call at all, or fall back immediately."""
        try:
            with urllib.request.urlopen(self.tags_url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, socket.timeout, ValueError, OSError) as e:
            logger.warning("Ollama unreachable at %s: %s", self.tags_url, e)
            return False
        names = {m.get("name") for m in data.get("models", [])}
        if self.model not in names:
            logger.warning("Ollama is reachable but model '%s' is not pulled (available: %s)", self.model, sorted(names))
            return False
        return True

    def _call_ollama(self, user_content: str) -> Optional[str]:
        payload = json.dumps({
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.0},
            "messages": [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }).encode("utf-8")
        req = urllib.request.Request(
            self.chat_url, data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, socket.timeout, ValueError, OSError) as e:
            logger.warning("LLM judge call failed (%s): %s", self.chat_url, e)
            return None
        return (body.get("message") or {}).get("content")

    def evaluate_triad(self, prompt: str, context_text: str, response_text: str) -> Optional[Dict[str, Any]]:
        """Returns the same shape as RAGTriadEvaluator.evaluate_triad, plus
        `judge_mode`/`judge_model`/`rationale`, or None if the judge is
        unavailable/unparseable (caller should fall back to the substring
        scorer)."""
        if not response_text or not response_text.strip():
            # Deterministic short-circuit -- see module docstring's caveat:
            # even the LLM judge itself doesn't reliably self-correct here.
            return {
                "context_relevance": 0.0,
                "faithfulness": 0.0,
                "answer_relevance": 0.0,
                "triad_composite_score": 0.0,
                "triad_score_percent": "0.0%",
                "rationale": "Empty response -- scored 0 deterministically without calling the judge model.",
                "judge_mode": "deterministic_empty_response",
                "judge_model": None,
            }

        user_content = (
            f"QUESTION: {prompt}\n\n"
            f"RETRIEVED CONTEXT: {context_text}\n\n"
            f"GENERATED RESPONSE: {response_text}\n\n"
            "Evaluate the response per the schema."
        )
        raw = self._call_ollama(user_content)
        if raw is None:
            return None

        match = _JSON_OBJECT_RE.search(raw)
        if not match:
            logger.warning("LLM judge response was not parseable JSON: %r", raw[:200])
            return None
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            logger.warning("LLM judge response had a JSON-like span that failed to parse: %r", raw[:200])
            return None

        context_rel = _clamp01(parsed.get("context_relevance"))
        faithfulness = _clamp01(parsed.get("faithfulness"))
        answer_rel = _clamp01(parsed.get("answer_relevance"))
        composite = round((context_rel + faithfulness + answer_rel) / 3.0, 4)

        return {
            "context_relevance": round(context_rel, 4),
            "faithfulness": round(faithfulness, 4),
            "answer_relevance": round(answer_rel, 4),
            "triad_composite_score": composite,
            "triad_score_percent": f"{round(composite * 100, 1)}%",
            "rationale": str(parsed.get("rationale", ""))[:500],
            "judge_mode": "ollama_llm_judge",
            "judge_model": self.model,
        }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    print("🚀 Verifying LLM-as-Judge RAG Evaluation Engine (Ollama)...")
    print("=============================================================")

    judge = LLMJudgeEvaluator()
    if not judge.is_available():
        print(f"⚠️  Ollama not reachable or model '{judge.model}' not pulled at {judge.chat_url} -- "
              f"skipping self-test (this is a clean degrade, not a failure: callers fall back to "
              f"RAGTriadEvaluator's substring scorer in this case).")
        return

    sample_prompt = "Identify overdrawn deposit account customer risk exposure and master party entities"
    sample_context = "Table deposit_account has balance -250.00 for customer CUST-9824. Table party_individual contains customer name John Doe."
    sample_response = "Found overdrawn deposit account balance -250.00 for customer CUST-9824 under party_individual record."

    metrics = judge.evaluate_triad(sample_prompt, sample_context, sample_response)
    print("\n📊 LLM Judge Scorecard (real generated response):")
    for k, v in (metrics or {}).items():
        print(f"  🎯 {k}: {v}")
    assert metrics is not None, "Judge call failed against a reachable, pulled model -- investigate."

    empty_metrics = judge.evaluate_triad(sample_prompt, sample_context, "")
    print("\n📊 LLM Judge Scorecard (empty response -- must be all zeros, deterministically):")
    for k, v in (empty_metrics or {}).items():
        print(f"  🎯 {k}: {v}")
    assert empty_metrics["faithfulness"] == 0.0 and empty_metrics["answer_relevance"] == 0.0, \
        "Empty-response short-circuit regressed -- this is exactly the Q7 defect this module exists to fix."

    print("\n✅ LLM-as-Judge RAG Evaluation Engine Verification Complete!")


if __name__ == "__main__":
    main()
