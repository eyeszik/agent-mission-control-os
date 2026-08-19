from typing import List

# Heuristic list of unsubstantiated/regulated marketing claims that require human
# review before external publish. Not a substitute for legal/regulatory review.
BANNED_CLAIMS = [
    "guaranteed",
    "cure",
    "miracle",
    "clinically proven",
    "risk-free",
    "no side effects",
    "#1 in the world",
    "best in the universe",
    "instant results",
    "fda approved",
]


def check_brand_safety(text: str) -> List[str]:
    """
    Scans copy for unsubstantiated/regulated claims. Returns the list of matched
    terms (empty list means no heuristic issues were found).
    """
    if not text:
        return []
    lowered = text.lower()
    return [term for term in BANNED_CLAIMS if term in lowered]
