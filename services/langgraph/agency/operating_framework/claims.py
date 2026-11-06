"""Marketing claims found by their signals, not their length.

``project_os.knowledge.extract_claims`` keeps only sentences of six to sixty
words. That is right for ingesting sources and wrong for marketing copy, where
"Free" or "Save 30%" on a badge is a whole claim. This module finds claims in
copy deterministically (no model) and keeps four stages apart:

1. Detection: a markup segment or sentence is a claim when it carries a claim
   signal (price, quantity, comparison, absolute, environmental, subjective or
   factual wording). Navigation text such as "Learn more" carries none.
2. Substantiation: what a claim would need. Objective classes need evidence;
   puffery is reviewed as opinion. Whether evidence exists is decided by the
   caller from refs a person linked, never inferred here.
3. Policy: every claim is routed to human review. Nothing here rejects copy.
4. Decision: none. A person decides through the existing approval routes.

Qualifiers ("up to", "*", "on orders over") and quotations are recorded as
classes, because they change what a claim says; a quotation repeats a claim,
it does not substantiate it.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

PRICE = "PRICE"
QUANTIFIED = "QUANTIFIED"
COMPARATIVE = "COMPARATIVE"
ABSOLUTE = "ABSOLUTE"
ENVIRONMENTAL = "ENVIRONMENTAL"
SUBJECTIVE = "SUBJECTIVE"
FACTUAL = "FACTUAL"
QUALIFIED = "QUALIFIED"
THIRD_PARTY_QUOTE = "THIRD_PARTY_QUOTE"
CLASSES = (PRICE, QUANTIFIED, COMPARATIVE, ABSOLUTE, ENVIRONMENTAL, SUBJECTIVE, FACTUAL, QUALIFIED, THIRD_PARTY_QUOTE)
# Classes that make a segment a claim; qualifiers and quotation marks only modify one.
_SUBSTANTIVE = {PRICE, QUANTIFIED, COMPARATIVE, ABSOLUTE, ENVIRONMENTAL, SUBJECTIVE, FACTUAL}
_OBJECTIVE = {PRICE, QUANTIFIED, COMPARATIVE, ABSOLUTE, ENVIRONMENTAL, FACTUAL}

_NUMBER_WORDS = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|hundred|thousand|million|twice|double|half)"
_SIGNALS: dict[str, tuple[re.Pattern[str], ...]] = {
    PRICE: tuple(re.compile(p) for p in (
        r"\bfree\b", r"\bno (?:hidden |extra |monthly )?fees?\b", r"\bfee[- ]free\b", r"\bsave\b", r"\bsavings?\b",
        r"\bdiscount", r"\b\d+\s*% off\b", r"[$€£¥]\s?\d", r"\bprices?\b", r"\bcheap", r"\bat no (?:extra )?cost\b",
        r"\brefund", r"\bmoney[- ]back\b",
    )),
    QUANTIFIED: (re.compile(r"\d"), re.compile(rf"\b{_NUMBER_WORDS}\b")),
    COMPARATIVE: tuple(re.compile(p) for p in (
        r"\b\w+er than\b", r"\b(?:more|less|fewer) \w+(?: \w+)? than\b", r"\bversus\b", r"\bvs\.?(?=\s|$)",
        r"\bcompared (?:with|to)\b",
    )),
    ABSOLUTE: tuple(re.compile(p) for p in (
        r"\bbest\b", r"\bguarantee[ds]?\b", r"\balways\b", r"\bnever\b", r"#\s?1\b", r"\bnumber one\b", r"\b100\s?%",
        r"\b(?:lowest|cheapest|fastest|strongest|safest|healthiest)\b", r"\bunbeatable\b", r"\brisk[- ]free\b",
        r"\bforever\b", r"\bperfect\b", r"\bworld[- ]class\b", r"\bonly\b",
    )),
    ENVIRONMENTAL: tuple(re.compile(p) for p in (
        r"\bcarbon[- ]neutral\b", r"\bnet[- ]zero\b", r"\beco[- ]?friendly\b", r"\beco\b", r"\bsustainabl", r"\brecycl",
        r"\bbiodegradable\b", r"\bcompostable\b", r"\borganic\b", r"\bplastic[- ]free\b", r"\bclimate\b",
        r"\bzero[- ]waste\b", r"\bgreen energy\b",
    )),
    SUBJECTIVE: tuple(re.compile(p) for p in (
        r"\bfast\b", r"\bquick(?:ly)?\b", r"\beasy\b", r"\beasily\b", r"\bsimple\b", r"\bbeautiful", r"\bdelicious\b",
        r"\bpremium\b", r"\bamazing\b", r"\beffortless", r"\bpowerful\b", r"\bloved\b", r"\bawesome\b", r"\bstunning\b",
    )),
    FACTUAL: tuple(re.compile(p) for p in (
        r"\bships?\b", r"\bdeliver(?:s|ed|y)?\b", r"\bcontains?\b", r"\bmade (?:in|from|with)\b", r"\bcertified\b",
        r"\bincludes?\b", r"\brated\b", r"\b(?:used|trusted) by\b", r"\bapproved\b", r"\bclinically\b", r"\bproven\b",
        r"\bsince \d{4}\b", r"\bawarded\b",
    )),
}
_QUALIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((label, re.compile(p)) for label, p in (
    ("*", r"\*"), ("†", r"†"), ("up to", r"\bup to\b"), ("terms apply", r"\b(?:terms|conditions|t&cs?) apply\b"),
    ("may", r"\bmay\b"), ("typically", r"\btypically\b"), ("on orders over", r"\bon orders over\b"),
    ("for a limited time", r"\bfor a limited time\b"), ("while stocks last", r"\bwhile stocks last\b"),
    ("selected", r"\bselected\b"), ("subject to", r"\bsubject to\b"), ("from", r"\bfrom [$€£¥]\s?\d"),
    ("in most", r"\bin most\b"),
))
_QUOTE = re.compile(r'^"[^"]+"|"\s*(?:said|says|wrote)\b|\s[—–-]\s?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?\s*$')
_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
_MARKS = str.maketrans({"™": "", "®": "", "℠": "", "©": "", "“": '"', "”": '"', "‘": "'",
                        "’": "'", "«": '"', "»": '"'})
MAX_CLAIMS = 200
MAX_CHARS = 400


@dataclass(frozen=True)
class Claim:
    text: str
    normalized: str
    classes: tuple[str, ...]
    qualifiers: tuple[str, ...] = field(default_factory=tuple)
    ambiguous: bool = False

    @property
    def substantiation(self) -> str:
        return "EVIDENCE_REQUIRED" if set(self.classes) & _OBJECTIVE else "REVIEW_AS_OPINION"

    @property
    def policy_route(self) -> str:
        return "HUMAN_REVIEW"

    @property
    def decision(self) -> str:
        return "NONE: detection only; a person decides"

    def as_dict(self) -> dict:
        return {"text": self.text, "normalized": self.normalized, "classes": list(self.classes),
                "qualifiers": list(self.qualifiers), "ambiguous": self.ambiguous,
                "substantiation_need": self.substantiation, "policy_route": self.policy_route}


def _clean(segment: str) -> str:
    """Unicode-normalised, trademark marks dropped, curly quotes straightened, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", segment.translate(_MARKS))
    return " ".join(text.split())


def normalize(text: str) -> str:
    """The comparison key: casefolded, trailing full stops/exclamations dropped. ``*`` and ``?`` are kept."""
    return _clean(text).casefold().rstrip(" .!").strip()


def _segments(text: str) -> list[str]:
    plain = html.unescape(_TAG.sub("\n", text))
    out = []
    for part in _BREAK.split(plain):
        part = _clean(part)
        if part:
            out.append(part[:MAX_CHARS])
    return out


def classify(segment: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    lowered = _clean(segment).casefold()
    found = [name for name, patterns in _SIGNALS.items() if any(p.search(lowered) for p in patterns)]
    qualifiers = tuple(label for label, pattern in _QUALIFIERS if pattern.search(lowered))
    if qualifiers:
        found.append(QUALIFIED)
    if _QUOTE.search(_clean(segment)):
        found.append(THIRD_PARTY_QUOTE)
    return tuple(c for c in CLASSES if c in found), qualifiers


def detect_claims(text: str) -> list[Claim]:
    """Every claim-bearing segment of ``text`` (markup segments and sentences), in order."""
    claims: list[Claim] = []
    for segment in _segments(text):
        classes, qualifiers = classify(segment)
        if not set(classes) & _SUBSTANTIVE:
            continue
        claims.append(Claim(text=segment, normalized=normalize(segment), classes=classes, qualifiers=qualifiers,
                            ambiguous=segment.rstrip().endswith("?")))
        if len(claims) >= MAX_CLAIMS:
            break
    return claims


__all__ = ["CLASSES", "Claim", "classify", "detect_claims", "normalize"]
