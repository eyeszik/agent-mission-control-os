"""Optional local LLM scripting via Ollama.

Used only when an Ollama runtime is already running locally *and* has at least
one model pulled. It never pulls a model (that is a multi-gigabyte download),
never uses a credential, and never reaches beyond the configured loopback host.

When it is unavailable the deterministic template engine takes over, which is
why no part of the pipeline depends on this file existing.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from ..errors import ProviderUnavailable
from ..models import Project
from .base import Capability
from .script_template import (
    TemplateScriptProvider,
    WORDS_PER_SECOND,
    _shape,
    _titlecase,
)

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
PROBE_TIMEOUT_SECONDS = 1.5
GENERATE_TIMEOUT_SECONDS = 120.0

PROMPT = """You are a short-form video script writer.

Write a {scene_count}-beat voiceover script about: {topic}

{brief_block}Rules:
- Output ONLY valid JSON, no markdown fence, no commentary.
- Schema: {{"beats": [{{"role": str, "voiceover": str, "headline": str, "kicker": str}}]}}
- roles in order: {roles}
- "voiceover" is spoken narration, at most {max_words} words per beat, plain language.
- "headline" is 2-6 words for on-screen display, title case.
- "kicker" is 1-3 words, UPPERCASE.
- Do not invent statistics, dates, names or citations.
"""


class OllamaScriptProvider:
    """Local LLM scripting. Optional, never required."""

    name = "ollama"
    kind = "script"

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self.endpoint = os.environ.get("FVF_OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
        self.model = os.environ.get("FVF_OLLAMA_MODEL", "")
        self._models: list[str] = []
        self._fallback = TemplateScriptProvider()

    # -- discovery -------------------------------------------------------
    def _tags(self) -> Optional[list[str]]:
        try:
            request = urllib.request.Request(f"{self.endpoint}/api/tags")
            with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    return None
                payload = json.loads(response.read(262144).decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return None
        return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]

    def probe(self) -> Capability:
        remediation = (
            "Optional. To enable local LLM scripting:\n"
            "  1. Install Ollama (free, runs locally): https://ollama.com\n"
            "  2. Pull a small model, e.g. `ollama pull llama3.2:3b` "
            "(a multi-GB download you choose to make).\n"
            "  3. Optionally set FVF_OLLAMA_MODEL.\n"
            "Without it, the deterministic template engine is used."
        )
        models = self._tags()
        if models is None:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail=f"No Ollama runtime responded at {self.endpoint}.",
                remediation=remediation, requires_large_download=True,
                metadata={"endpoint": self.endpoint},
            )
        if not models:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail="Ollama is running but has no models pulled.",
                remediation=remediation, requires_large_download=True,
                metadata={"endpoint": self.endpoint},
            )
        self._models = models
        if self.model and self.model not in models:
            return Capability(
                available=False, name=self.name, kind=self.kind,
                detail=f"FVF_OLLAMA_MODEL={self.model!r} is not pulled. Have: "
                       f"{', '.join(models[:5])}",
                remediation=remediation, metadata={"endpoint": self.endpoint,
                                                   "models": models},
            )
        return Capability(
            available=True, name=self.name, kind=self.kind,
            detail="Local Ollama runtime with at least one model. Offline and free.",
            metadata={"endpoint": self.endpoint, "models": models,
                      "selected": self.model or models[0]},
        )

    # -- generation ------------------------------------------------------
    def generate(self, project: Project, scene_count: Optional[int] = None) -> dict[str, Any]:
        capability = self.probe()
        if not capability.available:
            raise ProviderUnavailable(capability.detail)
        model = self.model or self._models[0]

        # Start from the deterministic plan: it supplies the arc, the scene
        # count and the duration budget, so the LLM only has to write prose.
        base = self._fallback.generate(project)
        roles = [beat["role"] for beat in base["beats"]]
        max_words = max(6, int(min(b["target_duration"] for b in base["beats"])
                               * WORDS_PER_SECOND))
        brief_block = f"Source material (use it, do not contradict it):\n{project.brief}\n\n" \
            if project.brief.strip() else ""
        prompt = PROMPT.format(
            scene_count=len(roles),
            topic=project.topic,
            brief_block=brief_block,
            roles=", ".join(roles),
            max_words=max_words,
        )

        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.7, "seed": project.seed},
            }
        ).encode("utf-8")
        try:
            request = urllib.request.Request(
                f"{self.endpoint}/api/generate", data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=GENERATE_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"Ollama generation failed: {exc}") from exc

        beats = self._parse(payload.get("response", ""), roles)
        if not beats:
            raise ProviderUnavailable("Ollama returned no parsable beats")

        # Merge: LLM prose, deterministic timing. The timing model already
        # accounts for the real speaking rate, so it stays authoritative.
        merged = []
        for index, (template_beat, llm_beat) in enumerate(zip(base["beats"], beats)):
            voiceover = llm_beat.get("voiceover") or template_beat["voiceover"]
            words = len(voiceover.split())
            merged.append(
                {
                    **template_beat,
                    "voiceover": voiceover,
                    "headline": _titlecase(llm_beat.get("headline")
                                           or template_beat["headline"]),
                    "kicker": (llm_beat.get("kicker")
                               or template_beat["kicker"]).upper()[:22],
                    "word_count": words,
                    "target_duration": round(
                        max(template_beat["target_duration"],
                            words / WORDS_PER_SECOND + 0.55), 3),
                }
            )
        return {
            **base,
            "provider": self.name,
            "model": model,
            "shape": _shape(project.topic),
            "content_source": "local_llm",
            "content_source_note": (
                f"Body copy was written by the local model {model!r} via Ollama. "
                "Timing, arc and scene count come from the deterministic planner. "
                "Model output is not fact-checked."
            ),
            "beats": merged,
            "planned_duration": round(sum(b["target_duration"] for b in merged), 3),
            "total_words": sum(b["word_count"] for b in merged),
        }

    @staticmethod
    def _parse(raw: str, roles: list[str]) -> list[dict[str, str]]:
        """Parse the model's JSON defensively.

        Model output is untrusted data: it is parsed, type-checked and truncated,
        never executed or interpolated anywhere but as text.
        """
        text = (raw or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return []
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                return []
        raw_beats = payload.get("beats") if isinstance(payload, dict) else payload
        if not isinstance(raw_beats, list):
            return []
        beats: list[dict[str, str]] = []
        for item in raw_beats[: len(roles)]:
            if not isinstance(item, dict):
                continue
            beats.append(
                {
                    "voiceover": str(item.get("voiceover", ""))[:400],
                    "headline": str(item.get("headline", ""))[:80],
                    "kicker": str(item.get("kicker", ""))[:24],
                }
            )
        return beats if len(beats) == len(roles) else []
