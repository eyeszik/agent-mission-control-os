"""Deterministic script generation.

This provider is the reason FreeVideoForge never needs an LLM. It is a
narrative-structure compiler, not a fact generator, and it is explicit about
that distinction:

* When the caller supplies a ``brief`` with substance, the brief's own sentences
  become the body beats. The engine contributes structure, pacing and framing.
  ``content_source`` is then ``"brief"``.
* When only a topic is given, the engine emits a structural scaffold: a real
  hook, a real arc and a real payoff, phrased around the topic. It does **not**
  invent facts about the topic, and ``content_source`` is ``"scaffold"`` so no
  downstream consumer can mistake scaffolding for researched content.

Framing lines are authored as (narration, on-screen headline) pairs rather than
deriving the headline by truncating the narration, because a headline cut
mid-clause is the single most obvious tell of a generated video.

Everything is seeded: the same inputs always produce the same script, and a
different ``--seed`` produces a genuinely different variation.
"""

from __future__ import annotations

import random
import re
from typing import Any

from ..models import Project
from .base import Capability

# Words per second used to size copy against the requested duration. Tuned
# against espeak-ng's default rate (~175 wpm) with room for breathing space.
WORDS_PER_SECOND = 2.45

#: Minimum speakable words for a beat to be worth its own scene.
WORDS_PER_BEAT = 11

_QUESTION_LEAD_RE = re.compile(
    r"^(why|how|what|when|where|who|which|can|do|does|is|are|should|will)\b\s*", re.IGNORECASE
)
_LEADING_TO_RE = re.compile(r"^to\s+", re.IGNORECASE)
#: Verbs that commonly open a question topic ("What causes inflation").
_LEADING_VERBS = frozenset({
    "causes", "cause", "makes", "make", "drives", "drive", "creates", "create",
    "happens", "happen", "breaks", "break", "fixes", "fix", "explains", "explain",
    "kills", "kill", "affects", "affect",
})
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_SPLIT_RE = re.compile(r"[.?!;:—]|\s-\s")

_TRAILING_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "but",
    "is", "are", "was", "were", "by", "with", "that", "this", "as", "from",
    "into", "than", "then", "so", "it", "its", "your", "you", "we", "our",
}
_TITLE_SMALL = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "but",
    "is", "as", "by", "with", "from", "into", "than",
}
_LEADING_FILLER_RE = re.compile(
    r"^(it matters because|here is the|here is|here's|that is|that's|there is|"
    r"so |and |but |then |next |finally |start with |change that |keep the )",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _strip_terminal(text: str) -> str:
    return _clean(text).rstrip(".!?").strip()


def _titlecase(text: str) -> str:
    words = _strip_terminal(text).split()
    out = []
    for index, word in enumerate(words):
        lower = word.lower()
        out.append(word if word.isupper() and len(word) > 1
                   else (word.capitalize() if index == 0 or lower not in _TITLE_SMALL
                         else lower))
    return " ".join(out)


def _subject_phrase(topic: str) -> str:
    """'Why the moon changes shape' -> 'the moon changes shape'."""
    stripped = _strip_terminal(topic)
    without_lead = _QUESTION_LEAD_RE.sub("", stripped).strip()
    return without_lead or stripped


def _noun_phrase(topic: str) -> str:
    """A short noun-ish handle safe to drop into a sentence or an overlay.

    Cuts the subject phrase at its first connector and then at its first finite
    verb, so 'Why the moon changes shape' yields 'the moon' rather than a clause
    that cannot sit inside 'That is ...'. A gerund that is acting as a noun
    ('quantum computing') is kept.
    """
    subject = _LEADING_TO_RE.sub("", _subject_phrase(topic)).strip() or _subject_phrase(topic)
    for connector in (" to ", " for ", " that ", " which ", " with ", " and ", " in ", " on "):
        subject = subject.split(connector)[0]
    words = subject.split()
    if len(words) > 1 and words[0].lower() in _LEADING_VERBS:
        words = words[1:]
    determiners = {"the", "a", "an", "this", "these", "those", "my", "your", "our"}
    for position, word in enumerate(words[1:], start=1):
        lower = word.lower().strip(",")
        previous = words[position - 1].lower()
        if lower in {"is", "are", "was", "were", "do", "does", "did", "can", "will",
                     "has", "have", "gets", "get", "makes", "make", "works", "work"}:
            return " ".join(words[:position]) or subject
        inflected = (
            lower.endswith("ing")
            or lower.endswith("ed")
            or (lower.endswith("s") and not lower.endswith(("ss", "us", "is", "ics")))
        )
        # An inflected word only reads as a verb when it follows a determined
        # noun or sits deep in the phrase; otherwise it is part of the noun.
        if inflected and (previous in determiners or position >= 2):
            return " ".join(words[:position]) or subject
    return " ".join(words[:4])


def _is_question(topic: str) -> bool:
    return topic.strip().endswith("?") or bool(_QUESTION_LEAD_RE.match(topic.strip()))


def _shape(topic: str) -> str:
    """Classify the brief into a narrative shape."""
    lowered = topic.lower()
    if re.search(r"\bhow to\b|\bstep\b|\bsteps\b|\bguide\b|\btutorial\b", lowered):
        return "how_to"
    if re.search(r"\b\d+\s+(ways|things|reasons|tips|rules|signs|myths|mistakes)\b", lowered):
        return "listicle"
    if re.search(r"\bmyth|\bwrong\b|\bmistake|\bactually\b|\btruth\b", lowered):
        return "myth_bust"
    if re.search(r"\bvs\.?\b|\bversus\b|\bcompared? to\b", lowered):
        return "comparison"
    if _is_question(topic):
        return "question"
    return "explainer"


# --------------------------------------------------------------------------
# Authored copy pools: (narration, on-screen headline)
# Each pool is ordered short -> long so a tight word budget still gets a
# complete, grammatical line instead of a truncated one.
# --------------------------------------------------------------------------

Pair = tuple[str, str]

_HOOKS: dict[str, tuple[Pair, ...]] = {
    "question": (
        ("{Topic}?", "{Topic}?"),
        ("Short answer first, then the why.", "Short Answer First"),
        ("{Topic}? The answer is simpler than most people expect.", "Simpler Than You Think"),
        ("Almost everyone answers this the same way, and almost everyone is off by one step.",
         "Off By One Step"),
    ),
    "explainer": (
        ("{Noun}, explained properly.", "{Noun}, Explained"),
        ("You were probably taught the tidy version.", "The Tidy Version Is Wrong"),
        ("There is a reason {subject}, and it is not the one you were taught.",
         "Not the Reason You Were Taught"),
        ("Most explanations of {noun} skip the one part that actually does the work.",
         "The Part Everyone Skips"),
    ),
    "how_to": (
        ("{Topic}. Without the filler.", "No Filler"),
        ("The fast version, start to finish.", "Start to Finish"),
        ("Skip the theory. Here is the version that survives contact with reality.",
         "Skip the Theory"),
        ("Every guide gives you twelve steps. You need three, and they are in order.",
         "Three Steps, In Order"),
    ),
    "listicle": (
        ("{Topic}.", "{Topic}"),
        ("Short, usable, and in order.", "In Order"),
        ("{Topic}. The last one reframes everything above it.", "The Last One Reframes It"),
        ("None of these need a budget, and all of them work today.", "All Of Them Work Today"),
    ),
    "myth_bust": (
        ("This one does not hold up.", "It Does Not Hold Up"),
        ("You have heard this a hundred times.", "Heard It A Hundred Times"),
        ("You have probably heard this about {noun}. It does not survive a second look.",
         "It Does Not Survive A Second Look"),
        ("The popular version is not wrong exactly. It is wrong in the part that matters.",
         "Wrong Where It Matters"),
    ),
    "comparison": (
        ("{Topic}. Not the same thing.", "Not the Same Thing"),
        ("One real difference. Here it is.", "One Real Difference"),
        ("{Topic}. They are not interchangeable, and the difference is the whole point.",
         "The Difference Is the Point"),
        ("People argue about this constantly without ever naming the actual trade-off.",
         "Name the Trade-off"),
    ),
}

_CONTEXT: tuple[Pair, ...] = (
    ("It matters more than it looks.", "Why It Matters"),
    ("The wrong mental model quietly costs you time.", "The Cost Of A Bad Model"),
    ("Getting this right changes what you do next, not just what you know.",
     "It Changes What You Do"),
    ("This is one of those ideas that only looks complicated from the outside.",
     "Complicated From Outside Only"),
)

#: Used only when no brief is supplied. Structural prompts, never factual claims.
_SCAFFOLD: tuple[Pair, ...] = (
    ("Start with what you can actually observe.", "Start With What You See"),
    ("Then the mechanism, in the order it happens.", "The Mechanism, In Order"),
    ("Then the condition that has to hold for any of it to work.", "The Condition"),
    ("Then the test. A good explanation survives it.", "The Test"),
    ("Everything else is detail layered on top of that one shape.", "The Rest Is Detail"),
)

_TURN: tuple[Pair, ...] = (
    ("Here is the turn.", "The Turn"),
    ("The framing was the problem all along.", "The Framing Was The Problem"),
    ("The confusing part was never the subject. It was the frame around it.",
     "It Was Never The Subject"),
    ("Change that one assumption and the whole picture reorders itself.",
     "One Assumption, Reordered"),
)

_PAYOFF: tuple[Pair, ...] = (
    ("Keep the shape. Forget the trivia.", "Keep The Shape"),
    ("If you remember one thing, make it that.", "Remember One Thing"),
    ("Fix the frame and the rest of it follows on its own.", "Fix The Frame"),
    ("That is the whole idea, end to end, without the noise.", "End To End"),
)

_KICKERS: dict[str, tuple[str, ...]] = {
    "hook": ("START HERE", "THE SETUP", "FIRST"),
    "context": ("WHY IT MATTERS", "THE STAKES", "CONTEXT"),
    "body": ("THE MECHANISM", "HOW IT WORKS", "THE DETAIL", "THE CONDITION", "THE TEST"),
    "turn": ("THE TURN", "THE INSIGHT", "THE SHIFT"),
    "payoff": ("THE TAKEAWAY", "REMEMBER THIS", "IN ONE LINE"),
}

_ROLE_WEIGHT = {"hook": 1.15, "context": 0.95, "body": 1.0, "turn": 0.9, "payoff": 1.1}


def _fill(template: str, ctx: dict[str, str]) -> str:
    return _clean(template.format(**ctx))


def _brief_sentences(brief: str) -> list[str]:
    parts = [_clean(p) for p in _SENTENCE_SPLIT_RE.split(_clean(brief))]
    return [p for p in parts if len(p.split()) >= 3]


def _condense(sentence: str, max_words: int) -> str:
    """Trim a brief-supplied sentence to a clause boundary inside the budget."""
    words = sentence.split()
    if len(words) <= max_words:
        return sentence
    for marker in ("; ", " — ", ", and ", ", but ", ", which ", ", so ", ", "):
        head = sentence.split(marker)[0]
        if 4 <= len(head.split()) <= max_words:
            return head.rstrip(",;: ") + "."
    kept = words[:max_words]
    while kept and kept[-1].lower().strip(",;:") in _TRAILING_STOPWORDS:
        kept.pop()
    return " ".join(kept).rstrip(",;: ") + "."


def _derive_headline(text: str, max_words: int = 6) -> str:
    """Headline for brief-sourced copy, cut at a clause boundary."""
    clause = _CLAUSE_SPLIT_RE.split(_clean(text))[0]
    clause = _LEADING_FILLER_RE.sub("", clause).strip()
    words = clause.split()
    if len(words) > max_words:
        words = words[:max_words]
        while words and words[-1].lower().strip(",;:") in _TRAILING_STOPWORDS:
            words.pop()
    return _titlecase(" ".join(words) or clause)


class TemplateScriptProvider:
    """Seeded, offline, dependency-free script generation.

    Always available. This is the floor that guarantees the pipeline can run
    with no LLM of any kind.
    """

    name = "template"
    kind = "script"

    def probe(self) -> Capability:
        return Capability(
            available=True,
            name=self.name,
            kind=self.kind,
            detail="Deterministic narrative-structure compiler. No model, no network, "
                   "no credentials.",
            version="1.0.0",
            metadata={"words_per_second": WORDS_PER_SECOND},
        )

    # -- planning --------------------------------------------------------
    @staticmethod
    def suggest_scene_count(duration: float) -> int:
        """Scene count driven by the spoken word budget, not by clock time.

        Sizing beats from the word budget is what stops a short video from being
        chopped into scenes too small to say anything.
        """
        return max(2, min(12, int((duration * WORDS_PER_SECOND) // WORDS_PER_BEAT)))

    @staticmethod
    def _role_plan(scene_count: int) -> list[str]:
        """Narrative arc sized to the scene count. Hook and payoff always exist."""
        if scene_count <= 2:
            return ["hook", "payoff"]
        if scene_count == 3:
            return ["hook", "body", "payoff"]
        if scene_count == 4:
            return ["hook", "context", "body", "payoff"]
        return ["hook", "context"] + ["body"] * (scene_count - 4) + ["turn", "payoff"]

    @staticmethod
    def _pick(pool: tuple[Pair, ...], ctx: dict[str, str], budget: int,
              rng: random.Random, used: set[str]) -> Pair:
        """Pick the richest unused variant that fits the word budget.

        Framing lines are selected to fit, never truncated to fit: a hook cut
        mid-clause reads as a bug, and the scene's duration can grow instead.
        """
        filled = [(_fill(line, ctx), _fill(head, ctx)) for line, head in pool]
        fitting = [p for p in filled if len(p[0].split()) <= budget]
        pool_to_use = fitting or [min(filled, key=lambda p: len(p[0].split()))]
        fresh = [p for p in pool_to_use if p[0] not in used] or pool_to_use
        longest = max(len(p[0].split()) for p in fresh)
        best = [p for p in fresh if len(p[0].split()) >= longest - 3]
        choice = rng.choice(best)
        used.add(choice[0])
        return choice

    # -- generation ------------------------------------------------------
    def generate(self, project: Project) -> dict[str, Any]:
        rng = random.Random(project.seed)
        topic = _clean(project.topic)
        subject = _subject_phrase(topic)
        noun = _noun_phrase(topic)
        ctx = {
            "topic": topic,
            "Topic": _titlecase(topic),
            "subject": subject,
            "Subject": (subject[0].upper() + subject[1:]) if subject else subject,
            "noun": noun,
            "Noun": _titlecase(noun),
        }

        shape = _shape(topic)
        requested = project.providers.get("_scene_count")
        scene_count = int(requested) if requested else self.suggest_scene_count(project.duration)

        sentences = _brief_sentences(project.brief)
        content_source = "brief" if len(sentences) >= 2 else "scaffold"

        roles = self._role_plan(scene_count)
        weights = [_ROLE_WEIGHT[role] for role in roles]
        total_weight = sum(weights) or 1.0
        allocations = [project.duration * w / total_weight for w in weights]

        body_pool = list(sentences)
        used: set[str] = set()
        beats: list[dict[str, Any]] = []

        for index, (role, allocated) in enumerate(zip(roles, allocations)):
            budget = max(5, int(allocated * WORDS_PER_SECOND))
            if role == "body" and body_pool:
                # Brief-sourced copy is the user's content: condensing it to a
                # clause boundary is safe, inventing around it is not.
                line = _condense(body_pool.pop(0), budget)
                headline = _derive_headline(line)
            else:
                pool = {
                    "hook": _HOOKS.get(shape, _HOOKS["explainer"]),
                    "context": _CONTEXT,
                    "body": _SCAFFOLD,
                    "turn": _TURN,
                    "payoff": _PAYOFF,
                }[role]
                line, headline = self._pick(pool, ctx, budget, rng, used)

            words = len(line.split())
            # Copy drives duration; duration never silently truncates copy.
            needed = words / WORDS_PER_SECOND + 0.55
            kickers = _KICKERS[role]
            beats.append(
                {
                    "index": index,
                    "role": role,
                    "voiceover": line,
                    "headline": headline,
                    "kicker": kickers[index % len(kickers)],
                    "allocated_duration": round(allocated, 3),
                    "target_duration": round(max(allocated, needed), 3),
                    "word_count": words,
                }
            )

        planned = sum(beat["target_duration"] for beat in beats)
        note = ""
        if planned > project.duration + 0.01:
            note = (
                f"Copy needs {planned:.2f}s, which exceeds the requested "
                f"{project.duration:.2f}s. Scenes were extended rather than the "
                "narration being cut."
            )
        elif planned > 0:
            scale = project.duration / planned
            for beat in beats:
                beat["target_duration"] = round(beat["target_duration"] * scale, 3)
            planned = sum(beat["target_duration"] for beat in beats)

        return {
            "schema_version": "freevideoforge/script/v1",
            "title": _titlecase(topic),
            "topic": topic,
            "shape": shape,
            "intent": project.intent,
            "audience": project.audience,
            "format": project.format,
            "language": project.language,
            "narration_strategy": project.narration_strategy,
            "content_source": content_source,
            "content_source_note": (
                "Body copy was taken from the supplied brief; structure, pacing and "
                "framing lines are generated."
                if content_source == "brief"
                else "No brief was supplied, so body copy is a generated narrative "
                     "scaffold phrased around the topic. It asserts no facts about "
                     "the topic. Supply --brief to drive the body with real content."
            ),
            "provider": self.name,
            "model": None,
            "seed": project.seed,
            "target_duration": round(project.duration, 3),
            "planned_duration": round(planned, 3),
            "duration_note": note,
            "words_per_second": WORDS_PER_SECOND,
            "beats": beats,
            "unused_brief_sentences": body_pool,
            "total_words": sum(beat["word_count"] for beat in beats),
        }
