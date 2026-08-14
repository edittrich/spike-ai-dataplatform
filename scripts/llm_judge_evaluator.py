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
adds a real semantic judge using whichever model LLM_PROVIDER selects, already required by
`scripts/agentic_tool_runner.py` (`gemma4:latest`, confirmed present
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
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

# This module is both imported (by evaluate_agentic_retrieval.py, which loads
# .env itself) and run directly for its own self-test. Loading here too makes
# the standalone path work: without it, `python3 scripts/llm_judge_evaluator.py`
# saw no MOONSHOT_API_KEY and the backend correctly refused to start. Idempotent.
load_env()

from scripts._llm_backend import LLMBackendError, get_llm_backend  # noqa: E402

logger = logging.getLogger("LLMJudgeEvaluator")

# Cold model load was observed live at ~6.3s on Ollama; a remote Kimi call with
# reasoning tokens is slower still, so the default is generous. Overridable.
LLM_JUDGE_TIMEOUT_SECONDS = float(os.getenv("LLM_JUDGE_TIMEOUT_SECONDS", "120"))

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
    """Real semantic RAG-Triad scoring via the configured LLM provider. See module
    docstring for the fail-open contract and the empty-response caveat."""

    def __init__(self, model: Optional[str] = None, timeout: Optional[float] = None,
                 backend=None):
        self.timeout = timeout if timeout is not None else LLM_JUDGE_TIMEOUT_SECONDS
        self.backend = backend or get_llm_backend()
        if model:
            self.backend.model = model
        self.model = self.backend.model
        self.model_label = self.backend.model_label
        # Set by _call_llm() when the provider refused the deterministic
        # temperature this judge asks for -- surfaced in evaluate_triad()'s
        # result so a score can never be reported as reproducible when it
        # isn't. `kimi-k2.6` is exactly that case (only temperature=1).
        self.deterministic = True

    def is_available(self) -> bool:
        """Reachability + model-presence check against whichever provider is
        configured -- lets a caller decide whether to attempt the (slower)
        judge call at all, or fall back immediately."""
        ok, detail = self.backend.is_available()
        if not ok:
            logger.warning("LLM judge unavailable: %s", detail)
        return ok

    def _call_llm(self, user_content: str) -> Optional[str]:
        """Requests temperature 0.0 for reproducible scoring. A provider that
        refuses it (see LLMResponse.temperature_honored) still answers, but
        the score is no longer deterministic and says so."""
        try:
            result = self.backend.chat(
                [
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                timeout=self.timeout,
            )
        except LLMBackendError as e:
            logger.warning("LLM judge call failed: %s", e)
            return None
        if not result.temperature_honored:
            self.deterministic = False
        return result.content

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
        raw = self._call_llm(user_content)
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
            "judge_mode": f"{self.backend.provider}_llm_judge",
            "judge_model": self.model_label,
            # False when the provider refused temperature=0.0 (e.g. kimi-k2.6
            # accepts only 1), meaning this score is NOT reproducible run to run.
            "deterministic": self.deterministic,
        }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    print("🚀 Verifying LLM-as-Judge RAG Evaluation Engine...")
    print("=============================================================")

    try:
        judge = LLMJudgeEvaluator()
    except LLMBackendError as e:
        print(f"❌ LLM backend misconfigured: {e}")
        return
    print(f"   Provider: {judge.backend.provider} | Model: {judge.model_label}")
    if not judge.is_available():
        print(f"⚠️  Judge model '{judge.model_label}' is not reachable -- skipping self-test "
              f"(this is a clean degrade, not a failure: callers fall back to "
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
