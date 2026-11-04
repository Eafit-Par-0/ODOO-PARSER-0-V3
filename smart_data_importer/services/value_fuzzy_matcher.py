from dataclasses import dataclass

from rapidfuzz import fuzz, process


@dataclass(frozen=True)
class Suggestion:
    key: object      # selection key or record id
    label: str       # normalized label of the candidate
    score: float     # 0-100
    ambiguous: bool


def suggest(norm_value, candidates, threshold=80.0, margin=5.0):
    """Return the closest candidate or None.

    :param norm_value: value already normalized with normalize_text()
    :param candidates: list of (key, normalized_label)
    """
    if not norm_value or not candidates:
        return None
    labels = [label for _key, label in candidates]
    # the same record can appear several times (one label per language), so
    # ambiguity is measured against the best result with a DIFFERENT key
    top = process.extract(norm_value, labels, scorer=fuzz.ratio, limit=10)
    if not top or top[0][1] < threshold:
        return None
    best_label, best_score, best_idx = top[0]
    best_key = candidates[best_idx][0]
    other = next((t for t in top[1:] if candidates[t[2]][0] != best_key), None)
    ambiguous = other is not None and (best_score - other[1]) < margin
    return Suggestion(best_key, best_label, best_score, ambiguous)
