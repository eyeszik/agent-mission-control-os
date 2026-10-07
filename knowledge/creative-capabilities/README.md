# Creative capability registry

`registry.json` (schema `amc-creative-capabilities/v1`) declares every capability the creative runtime may plan with. `services/langgraph/agency/creative/capabilities.py` loads it; see `docs/creative-runtime.md` for how the runtime uses it.

## Fields

Each capability records:

- **Identity and placement:** `id`, `version`, the `stages` and `artifact_types` it serves, and what it `provides` and `consumes`.
- **Relationships:** dependencies and conflicts.
- **Cost profile:** cost, latency and idempotency classes.
- **Binding:** its validators and the `implementation` (`module:attribute`).
- **Provenance:** `source_provenance`, with the SHA-256 of every workflow guide it was derived from and the existing repository owner it reuses.

## Dispositions

Every capability gets exactly one disposition:

| Disposition | Meaning |
|---|---|
| `REUSE_EXISTING` | an existing repository function is the implementation (e.g. `render_logo_svg`, `compile_uiux`) |
| `COMPOSE_EXISTING` | new code built on existing owners (e.g. the accessibility critic on `dom_audit`) |
| `EXTEND_EXISTING` | extends an owner's behaviour (context portfolio over the validated design-corpus loader) |
| `ADD_NEW` | no owner existed (mission compiler, organization compiler, search, TriDiff) |
| `DOCUMENTATION_ONLY` | guidance retained; nothing executes (`status: guidance_only`) |
| `BLOCKED` | needs a provider or authority the repository does not have (`status: provider_gap`) |

Semantic duplicates were merged rather than registered twice. The two accessibility guides, `accessibility-review.md` and `eyeszik-claude-design-skills-accessibility.md`, back the single `cap.critic.accessibility`.

## Guides

`guides/*.md` are the 20 workflow guides from the supplied creative corpus, copied verbatim and hash-pinned in the registry. They are advisory workflow guidance, and the context optimizer forwards only each guide's "Core constraint:" line. They never define runtime policy, permissions or brand state.

They were not moved into the design corpus's `standards/`, because that would raise their authority. A guide whose hash no longer matches degrades its capability, and a guide that trips the injection scanner is quarantined.

## Changing the registry

Edit `registry.json` deliberately and recompute a guide's `sha256` only after reviewing the new guide text. Then run:

```bash
python -m pytest services/langgraph/tests/test_creative_runtime.py -q
```

Registering an identical definition twice is a no-op; a different definition under an existing id is refused.
