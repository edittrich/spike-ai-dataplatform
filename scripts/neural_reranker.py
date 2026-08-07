#!/usr/bin/env python3
"""
===============================================================================
2nd-Stage Neural Re-Ranking Engine (Cross-Encoder)
===============================================================================
Performs deep cross-attention neural re-ranking over 1st-stage `pgvector` candidates:
1. 1st-Stage (Bi-Encoder Retrieval): pgvector HNSW cosine search retrieves top 10 candidates.
2. 2nd-Stage (Cross-Encoder Re-Ranking): CrossEncoder scores (query, candidate) pairs,
   re-ordering entities by deep semantic relevance.
===============================================================================
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging
from typing import List, Dict, Any

from scripts._embedding_backend import load_reranker_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("NeuralReranker")

# Fails closed by default (raises) if the real cross-encoder can't load -- set
# ALLOW_DEGRADED_EMBEDDINGS=1 to accept a lexical-overlap fallback instead.
# See scripts/_embedding_backend.py.
_score_pairs, _RERANK_MODE = load_reranker_model()

class NeuralReranker:
    def __init__(self):
        # Exposed per-instance (rather than only as a module-level constant)
        # so callers building a response payload -- see
        # scripts/hybrid_rag_retriever.py's hybrid_retrieve() -- can read
        # `self.reranker.mode` without importing this module's internals.
        self.mode = _RERANK_MODE

    def rerank_candidates(self, query: str, candidates: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Re-ranks 1st-stage candidates using Cross-Encoder cross-attention scoring.
        """
        if not candidates:
            return []

        pairs = [(query, c.get("content_text", c.get("display_name", ""))) for c in candidates]
        rerank_scores = _score_pairs(pairs)

        reranked = []
        for i, c in enumerate(candidates):
            item = dict(c)
            item["vector_similarity_score"] = item.get("similarity", 0.0)
            item["cross_encoder_score"] = rerank_scores[i]
            reranked.append(item)

        # Sort by 2nd-stage Cross-Encoder score descending
        reranked.sort(key=lambda x: x["cross_encoder_score"], reverse=True)
        return reranked[:top_k]

def main():
    print("🚀 Verifying 2nd-Stage Neural Re-Ranking Engine (Cross-Encoder)...")
    print("================================================================")

    query = "Find individual customer personal details date of birth and identity"
    candidates = [
        {"display_name": "deposit_account", "similarity": 0.482, "content_text": "Table: deposit_account. Description: BIAN Current & Savings accounts."},
        {"display_name": "party_individual", "similarity": 0.451, "content_text": "Table: party_individual. Description: Individual Person demographics name date of birth SSN identity."},
        {"display_name": "loan_agreement", "similarity": 0.395, "content_text": "Table: loan_agreement. Description: Loan principal amount interest rates."}
    ]

    reranker = NeuralReranker()
    results = reranker.rerank_candidates(query, candidates, top_k=3)

    print(f"\nQuery Prompt: '{query}'\n")
    print(f"Re-ranker mode: {reranker.mode}" + (" (DEGRADED -- lexical overlap, not a real cross-encoder)" if reranker.mode == "degraded" else ""))
    print("1st-Stage Vector Rank vs 2nd-Stage Neural Cross-Encoder Re-Ranked Results:")
    print("-------------------------------------------------------------------------")
    for idx, r in enumerate(results, 1):
        print(f"  🎯 Rank #{idx}: `{r['display_name']}` — Cross-Encoder Score: {r['cross_encoder_score']} (Vector Similarity: {r['vector_similarity_score']})")

    print(f"\n✅ 2nd-Stage Neural Re-Ranking Engine self-test complete (mode: {reranker.mode}).")

if __name__ == "__main__":
    main()
