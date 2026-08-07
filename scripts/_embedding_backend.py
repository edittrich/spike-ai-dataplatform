#!/usr/bin/env python3
"""
===============================================================================
Shared Embedding & Cross-Encoder Model Loader (fail-closed by default)
===============================================================================
scripts/hybrid_rag_retriever.py, scripts/neural_reranker.py, and
scripts/generate_vector_embeddings.py each used to carry their own copy of
"try to load the real sentence-transformers model, silently fall back to a
hash-based/lexical approximation on any failure." That fallback is not a
degraded version of the real thing -- it's a different, non-semantic
computation returned under the same field names (`embedding`,
`cross_encoder_score`) a real model would use, so nothing downstream (or the
calling agent) can tell the difference. The hash-based embedding fallback is
also *non-deterministic across processes*: Python's builtin `hash()` on `str`
is salted per interpreter unless `PYTHONHASHSEED` is fixed, so the same text
embedded in two different processes (e.g. once when indexing, once when
querying) lands in different vector dimensions entirely.

This module is the single place that decision gets made, and the default is
to fail loudly instead of silently: if the real model can't load, importing
this module's `load_embedding_model()` / `load_reranker_model()` raises,
unless `ALLOW_DEGRADED_EMBEDDINGS=1` is set in the environment -- in which
case the fallback is used, but every caller can also see `mode == "degraded"`
and is expected to tag results accordingly (see hybrid_rag_retriever.py's
`hybrid_retrieve()`), rather than let a degraded result look identical to a
real one.
===============================================================================
"""

import logging
import math
import os
import re
from typing import Callable, List, Tuple

logger = logging.getLogger("EmbeddingBackend")

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
ALLOW_DEGRADED_EMBEDDINGS = os.getenv("ALLOW_DEGRADED_EMBEDDINGS", "").strip() == "1"

EMBEDDING_DIM = 384


def _degraded_embed(text: str) -> List[float]:
    """Non-semantic fallback: character-trigram hash bag-of-words, L2-normalized.

    Not a substitute for real embeddings -- see module docstring. Kept only
    so the platform can still run end-to-end (with clearly-labeled degraded
    results) when the real model genuinely isn't available and the caller has
    explicitly opted in via ALLOW_DEGRADED_EMBEDDINGS=1.
    """
    vec = [0.0] * EMBEDDING_DIM
    for token in re.findall(r'\w+', text.lower()):
        for i in range(len(token)):
            h = hash(token[i:i + 3]) % EMBEDDING_DIM
            vec[h] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [round(x / norm, 6) if norm > 0 else 0.0 for x in vec]


def _degraded_score_pairs(pairs: List[Tuple[str, str]]) -> List[float]:
    """Non-semantic fallback: word-overlap ratio, not a cross-encoder score."""
    scores = []
    for query, doc in pairs:
        q_tokens = set(re.findall(r'\w+', query.lower()))
        d_tokens = re.findall(r'\w+', doc.lower())
        if not q_tokens or not d_tokens:
            scores.append(0.0)
            continue
        matches = sum(1 for t in d_tokens if t in q_tokens)
        scores.append(round(matches / math.sqrt(len(q_tokens) * len(d_tokens)), 4))
    return scores


def _refuse(component: str, model_name: str, error: Exception) -> None:
    raise RuntimeError(
        f"{component} model '{model_name}' failed to load ({error}) and "
        "ALLOW_DEGRADED_EMBEDDINGS is not set to '1'. Refusing to silently fall back to a "
        "non-semantic approximation reported under the same field names a real model would use "
        "-- that produces plausible-looking but mathematically meaningless results (and, for "
        "embeddings specifically, ones that aren't even stable across two runs of the same "
        "process). Install sentence-transformers + torch (see requirements.txt), or set "
        "ALLOW_DEGRADED_EMBEDDINGS=1 in .env to explicitly accept degraded retrieval."
    ) from error


def load_embedding_model() -> Tuple[Callable[[str], List[float]], str]:
    """Returns (encode_fn, mode) where mode is "real" or "degraded"."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)

        def encode_fn(text: str) -> List[float]:
            return [round(float(x), 6) for x in model.encode(text)]

        logger.info(f"Loaded embedding model '{EMBEDDING_MODEL_NAME}'.")
        return encode_fn, "real"
    except Exception as e:
        if not ALLOW_DEGRADED_EMBEDDINGS:
            _refuse("Embedding", EMBEDDING_MODEL_NAME, e)
        logger.warning(
            f"⚠️ DEGRADED embedding mode: '{EMBEDDING_MODEL_NAME}' unavailable ({e}); "
            "using a non-semantic lexical-hash fallback because ALLOW_DEGRADED_EMBEDDINGS=1."
        )
        return _degraded_embed, "degraded"


def load_reranker_model() -> Tuple[Callable[[List[Tuple[str, str]]], List[float]], str]:
    """Returns (score_pairs_fn, mode) where mode is "real" or "degraded"."""
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(RERANKER_MODEL_NAME)

        def score_fn(pairs: List[Tuple[str, str]]) -> List[float]:
            return [round(float(s), 4) for s in model.predict(pairs)]

        logger.info(f"Loaded cross-encoder model '{RERANKER_MODEL_NAME}'.")
        return score_fn, "real"
    except Exception as e:
        if not ALLOW_DEGRADED_EMBEDDINGS:
            _refuse("Cross-encoder", RERANKER_MODEL_NAME, e)
        logger.warning(
            f"⚠️ DEGRADED re-ranking mode: '{RERANKER_MODEL_NAME}' unavailable ({e}); "
            "using lexical token-overlap because ALLOW_DEGRADED_EMBEDDINGS=1."
        )
        return _degraded_score_pairs, "degraded"
