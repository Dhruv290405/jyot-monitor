"""Evaluation metric calculations: CER, WER, F1, NDCG@k, and security metrics."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
from rapidfuzz.distance import Levenshtein


class EvaluationMetrics:
    """Computes comprehensive evaluation metrics."""

    @staticmethod
    def calculate_cer(reference: str, hypothesis: str) -> float:
        """Computes Character Error Rate (CER)."""
        ref = reference.strip()
        hyp = hypothesis.strip()
        if not ref:
            return 0.0 if not hyp else 1.0
        dist = Levenshtein.distance(ref, hyp)
        return round(float(dist / len(ref)), 4)

    @staticmethod
    def calculate_wer(reference: str, hypothesis: str) -> float:
        """Computes Word Error Rate (WER)."""
        ref_words = reference.strip().split()
        hyp_words = hypothesis.strip().split()
        if not ref_words:
            return 0.0 if not hyp_words else 1.0

        # Levenshtein distance over word tokens
        d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
        for i in range(len(ref_words) + 1):
            d[i][0] = i
        for j in range(len(hyp_words) + 1):
            d[0][j] = j

        for i in range(1, len(ref_words) + 1):
            for j in range(1, len(hyp_words) + 1):
                if ref_words[i - 1] == hyp_words[j - 1]:
                    d[i][j] = d[i - 1][j - 1]
                else:
                    d[i][j] = min(
                        d[i - 1][j] + 1,      # deletion
                        d[i][j - 1] + 1,      # insertion
                        d[i - 1][j - 1] + 1,  # substitution
                    )

        dist = d[len(ref_words)][len(hyp_words)]
        return round(float(dist / len(ref_words)), 4)

    @staticmethod
    def calculate_classification_metrics(
        y_true: List[str], y_pred: List[str]
    ) -> Dict[str, float]:
        """Calculates Macro Precision, Recall, and F1."""
        if not y_true or not y_pred:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "accuracy": 0.0}

        classes = sorted(list(set(y_true).union(set(y_pred))))
        correct_total = sum(1 for t, p in zip(y_true, y_pred) if t == p)
        accuracy = correct_total / len(y_true)

        precisions = []
        recalls = []

        for cls in classes:
            tp = sum(1 for t, p in zip(y_true, y_pred) if t == cls and p == cls)
            fp = sum(1 for t, p in zip(y_true, y_pred) if t != cls and p == cls)
            fn = sum(1 for t, p in zip(y_true, y_pred) if t == cls and p != cls)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0 if fn == 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0

            precisions.append(prec)
            recalls.append(rec)

        macro_p = sum(precisions) / len(precisions) if precisions else 0.0
        macro_r = sum(recalls) / len(recalls) if recalls else 0.0
        macro_f1 = (
            (2 * macro_p * macro_r) / (macro_p + macro_r)
            if (macro_p + macro_r) > 0
            else 0.0
        )

        return {
            "accuracy": round(accuracy, 4),
            "macro_precision": round(macro_p, 4),
            "macro_recall": round(macro_r, 4),
            "macro_f1": round(macro_f1, 4),
        }

    @staticmethod
    def calculate_ndcg_at_k(
        predicted_rankings: List[str],
        gold_relevance_scores: Dict[str, float],
        k: int = 5,
    ) -> float:
        """Computes Normalized Discounted Cumulative Gain at rank k (NDCG@k)."""
        top_k = predicted_rankings[:k]
        dcg = 0.0
        for i, item_id in enumerate(top_k):
            rel = gold_relevance_scores.get(item_id, 0.0)
            dcg += (2**rel - 1) / math.log2(i + 2)

        # Ideal ranking
        ideal_rels = sorted(gold_relevance_scores.values(), reverse=True)[:k]
        idcg = sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(ideal_rels))

        if idcg == 0.0:
            return 1.0 if dcg == 0.0 else 0.0

        return round(float(dcg / idcg), 4)

    @staticmethod
    def calculate_percentiles(values: List[float]) -> Dict[str, float]:
        """Calculates min, p50, p95, and max percentiles."""
        if not values:
            return {"p50": 0.0, "p95": 0.0, "max": 0.0, "min": 0.0}
        s = sorted(values)
        n = len(s)
        p50_idx = int(0.50 * (n - 1))
        p95_idx = int(0.95 * (n - 1))
        return {
            "min": round(s[0], 3),
            "p50": round(s[p50_idx], 3),
            "p95": round(s[p95_idx], 3),
            "max": round(s[-1], 3),
        }
