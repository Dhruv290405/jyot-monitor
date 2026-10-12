"""Topic taxonomy and item classification."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from jyot_monitor.schemas import ClassificationResult


class TopicClassifier:
    """Classifies items into the public safety topic taxonomy."""

    TAXONOMY = {
        "Food & Drug Safety": [
            r"(?i)\b(fda|recall|salmonella|listeria|e\.?\s*coli|contamination|allergen|peanut|milk|adulterat|drug|medicine|pharmaceutical|undeclared\s+egg)\b",
            r"(?i)\b(food\s+poisoning|botulism|infant\s+formula|foreign\s+material|metal\s+fragments)\b",
        ],
        "Consumer Product Hazard": [
            r"(?i)\b(cpsc|choking|fire\s+hazard|burn\s+hazard|lithium|battery\s+overheat|electric\s+shock|strangulation|tip-over)\b",
            r"(?i)\b(stroller|crib|helmet|defective\s+latch|faulty\s+brake|airbag|product\s+recall)\b",
        ],
        "Civic & Infrastructure Outage": [
            r"(?i)\b(boil\s+water|water\s+main\s+break|power\s+outage|blackout|grid\s+failure|pipeline|gas\s+leak)\b",
            r"(?i)\b(subway\s+delay|transit\s+suspension|bridge\s+closure|evacuation\s+route|civic\s+alert)\b",
        ],
        "Environmental & Chemical Hazard": [
            r"(?i)\b(chemical\s+spill|toxic|epa|air\s+quality|smog|hazardous\s+waste|fumes|chlorine\s+leak|ammonia)\b",
            r"(?i)\b(wildfire\s+smoke|acid\s+rain|groundwater\s+contamination|radiation)\b",
        ],
        "Medical & Health Advisory": [
            r"(?i)\b(cdc|outbreak|measles|avian\s+flu|mpox|quarantine|medical\s+device\s+defect|pacemaker|syringe)\b",
            r"(?i)\b(infection\s+cluster|hospital\s+alert|vaccine\s+advisory)\b",
        ],
    }

    def classify(self, text: str, structured_org: Optional[str] = None) -> ClassificationResult:
        """Classifies text into a taxonomy class."""
        if not text:
            return ClassificationResult(
                subtopic="General / Uncategorized",
                confidence=30.0,
                explanation="No text provided to classify.",
            )

        scores: Dict[str, int] = {}
        matched_keywords: Dict[str, List[str]] = {}

        for category, patterns in self.TAXONOMY.items():
            count = 0
            keywords = []
            for pat in patterns:
                matches = re.findall(pat, text)
                if matches:
                    count += len(matches)
                    keywords.extend([str(m) for m in matches[:3]])
            scores[category] = count
            matched_keywords[category] = keywords

        # Consider organization hints
        if structured_org:
            if "FDA" in structured_org or "USDA" in structured_org:
                scores["Food & Drug Safety"] = scores.get("Food & Drug Safety", 0) + 3
            elif "CPSC" in structured_org:
                scores["Consumer Product Hazard"] = scores.get("Consumer Product Hazard", 0) + 3
            elif "CDC" in structured_org:
                scores["Medical & Health Advisory"] = scores.get("Medical & Health Advisory", 0) + 3
            elif "EPA" in structured_org:
                scores["Environmental & Chemical Hazard"] = scores.get("Environmental & Chemical Hazard", 0) + 3

        # Find best category
        best_category = max(scores, key=scores.get)
        best_count = scores[best_category]

        if best_count == 0:
            return ClassificationResult(
                subtopic="General / Uncategorized",
                confidence=40.0,
                explanation="No distinct domain keywords found; classified as general.",
            )

        # Normalize confidence between 65% and 95%
        confidence = min(95.0, 65.0 + (best_count * 5.0))
        kw_str = ", ".join(matched_keywords.get(best_category, [])[:3])
        explanation = f"Matched {best_count} key terms ({kw_str}) in domain '{best_category}'."

        return ClassificationResult(
            subtopic=best_category,
            confidence=round(confidence, 1),
            explanation=explanation,
        )
