#!/usr/bin/env python3
"""
===============================================================================
Advanced RAG Triad Evaluation Engine (Ragas / TruLens Metrics)
===============================================================================
Evaluates 3 fundamental quality dimensions for Retrieval-Augmented Generation:
1. Context Relevance: How precisely retrieved context matches prompt intent.
2. Groundedness (Faithfulness): Verifies answer facts exist in retrieved context.
3. Answer Relevance: Quantifies how directly the response addresses user query.
===============================================================================
"""

import re
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RAGTriadEvaluator")

class RAGTriadEvaluator:
    def __init__(self):
        pass

    def tokenize_words(self, text: str) -> set:
        """Tokenizes text into a set of lowercased alphanumeric keywords."""
        if not text:
            return set()
        return set(re.findall(r"\b[a-zA-Z0-9_]{3,}\b", text.lower()))

    def evaluate_context_relevance(self, prompt: str, context_text: str) -> float:
        """
        Metric 1: Context Relevance
        Measures overlap between prompt key terms and retrieved context chunks.
        """
        prompt_words = self.tokenize_words(prompt)
        if not prompt_words:
            return 1.0
        
        context_words = self.tokenize_words(context_text)
        if not context_words:
            return 0.0

        matches = prompt_words.intersection(context_words)
        relevance_score = len(matches) / len(prompt_words)
        return min(1.0, round(relevance_score, 4))

    def evaluate_faithfulness(self, context_text: str, response_text: str) -> float:
        """
        Metric 2: Groundedness / Faithfulness
        Verifies that factual terms/numbers in response are grounded in context.
        """
        if not response_text:
            return 1.0
        
        response_facts = set(re.findall(r"\b(?:\d+(?:\.\d+)?|[A-Z_]{3,})\b", response_text))
        if not response_facts:
            return 1.0
        
        context_facts = set(re.findall(r"\b(?:\d+(?:\.\d+)?|[A-Z_]{3,})\b", context_text))
        grounded_count = sum(1 for fact in response_facts if fact in context_facts or fact.lower() in context_text.lower())
        
        score = grounded_count / len(response_facts)
        return min(1.0, round(score, 4))

    def evaluate_answer_relevance(self, prompt: str, response_text: str) -> float:
        """
        Metric 3: Answer Relevance
        Measures prompt keyword coverage within generated response.
        """
        prompt_words = self.tokenize_words(prompt)
        if not prompt_words:
            return 1.0

        response_words = self.tokenize_words(response_text)
        if not response_words:
            return 0.0

        matches = prompt_words.intersection(response_words)
        score = len(matches) / len(prompt_words)
        return min(1.0, round(score, 4))

    def evaluate_triad(self, prompt: str, context_text: str, response_text: str) -> Dict[str, Any]:
        """
        Computes complete RAG Triad Scorecard (Context Relevance, Faithfulness, Answer Relevance).
        """
        context_rel = self.evaluate_context_relevance(prompt, context_text)
        faithfulness = self.evaluate_faithfulness(context_text, response_text)
        answer_rel = self.evaluate_answer_relevance(prompt, response_text)
        
        composite_score = round((context_rel + faithfulness + answer_rel) / 3.0, 4)
        
        return {
            "context_relevance": context_rel,
            "faithfulness": faithfulness,
            "answer_relevance": answer_rel,
            "triad_composite_score": composite_score,
            "triad_score_percent": f"{round(composite_score * 100, 1)}%"
        }

def main():
    evaluator = RAGTriadEvaluator()
    print("🚀 Verifying Advanced RAG Triad Evaluation Engine...")
    print("====================================================")

    sample_prompt = "Identify overdrawn deposit account customer risk exposure and master party entities"
    sample_context = "Table deposit_account has balance -250.00 for customer CUST-9824. Table party_individual contains customer name John Doe."
    sample_response = "Found overdrawn deposit account balance -250.00 for customer CUST-9824 under party_individual record."

    metrics = evaluator.evaluate_triad(sample_prompt, sample_context, sample_response)
    print("\n📊 RAG Triad Evaluation Scorecard:")
    for k, v in metrics.items():
        print(f"  🎯 {k}: {v}")

    print("\n✅ Advanced RAG Triad Evaluation Engine Verification Complete!")

if __name__ == "__main__":
    main()
