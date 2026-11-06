# Questions that improve creative missions

Ask for a decision, its evidence, a counterexample and a next action—not a claim
that the result is "groundbreaking". Novelty and preference need comparative
human review; a prompt or compiler benchmark cannot establish either.

## The twelve highest-value questions

| Ask Mission Control | Require in the answer |
|---|---|
| 1. Whose problem are we solving, in which situation, and what should they do or understand afterward? | One audience, primary task and observable success criterion; assumptions separated from research |
| 2. Which foundations are current, applicable and genuinely approved? | Tenant/project, artifact versions, evidence refs and actual decision records; missing prerequisites remain blockers |
| 3. What can this path execute today, and what will it only plan or compile? | Supported entry point, provider/engine status, persisted output and unavailable integrations; never relabel PROMPT_PACKAGE_READY as generated media |
| 4. Which requirements are hard gates, and which are preferences? | Exact text, rights, accessibility and brand constraints checked before aesthetic ranking |
| 5. What must remain invariant, and which variables may change? | Stable voice, message, approved tokens/fonts and campaign anchors; declared composition, metaphor or narrative axes |
| 6. Can you offer genuinely different concepts while keeping the same brief and content? | Bounded alternatives with distinct theses, a comparison rubric and a human choice; no universal-originality claim |
| 7. Why were these guidance sections selected, and what did you exclude? | Typed routing reasons, source hashes, rejected/irrelevant material and context usage; no authority from retrieved prose |
| 8. How will the design behave in the difficult states? | Loading, empty, error, denied, degraded, keyboard and small-screen states; real checks distinguished from specifications |
| 9. What would falsify the story, brand promise or marketing claim? | Supporting sources, contradictions, rights/consent and unverified claims; no invented customers or revenue |
| 10. How does this candidate compare with a baseline on the same task? | Same inputs, rubric and environment; task performance and hard-gate failures separate from preference |
| 11. Where is time and context being spent, and what can we safely reuse? | Profiles plus unprofiled timings, cache bounds, invalidation/refusal tests and measured scope—not an assumed end-to-end gain |
| 12. What exactly is ready, what is blocked, and whose decision is next? | Distinct plan/execution/verification/release predicates; scoped approval, exact version/hash and smallest useful next action |

## Domain questions and acceptance evidence

### Visual UI/UX

1. What is the shortest understandable route to the user's primary goal, and
   which step creates the greatest uncertainty? Require a task flow and an
   observed user test before claiming usability improvement.
2. What information hierarchy, density and component behavior follow from the
   task rather than a fashionable visual style? Require a justified layout and
   an alternative with the same content.
3. Which responsive changes preserve meaning and action priority? Require
   behavior at named viewport sizes, long content, zoom and localization.
4. Which WCAG 2.2 criteria are applicable, and which have actually been tested?
   Require keyboard/focus, contrast, naming and state evidence at their tested
   scope. Token compilation or a contrast sample is not a full accessibility audit.
5. What does the user see when a model is unavailable, evidence is missing, an
   action is denied or a request is stale? Require truthful states and recovery,
   not a loading animation that conceals a blocker.

### Graphic design

6. What single visual idea communicates the message before decorative details?
   Require a concept thesis, focal hierarchy and a small-size readability check.
7. Which exact copy, counts, logo usage and spatial relationships are mandatory?
   Require exact-text and layout checks; an attractive image can still fail.
8. Which elements can be edited without changing the rest of the composition?
   Require locality and preservation comparisons, not a whole-image aesthetic score.
9. Which approved fonts, token values, reference roles and rights are supported
   by the selected engine? Require source/approval refs and explicit unsupported fields.
10. Does the output work at the actual export size and medium? Require correct
    dimensions, format, legibility, safe areas and decoded/read-back artifact bytes.

### Storytelling

11. Who wants what, what resists them, and what changes because of their actions?
    Require a causal beat sequence rather than disconnected attractive scenes.
12. What should the audience feel or understand at each beat, and what visual
    evidence carries that meaning? Require a beat-to-frame/copy map.
13. Which story facts are verified and which are proposed creative devices?
    Require a claim ledger; fictional examples must stay explicitly fictional.
14. How do voice, character, setting and key objects remain consistent across
    variations? Require declared invariants and continuity checks.
15. What can be removed without losing the story, and where is the next action
    earned? Require a shorter alternative and human comprehension feedback.

### Branding

16. What customer-relevant distinction can the brand credibly own? Require
    research-backed positioning and a counterexample, not a list of flattering adjectives.
17. How are qualitative brand principles translated into supported literal
    rendering values? Keep `brand_core` qualitative and use the existing approved
    token/rendering contracts for values and fonts.
18. Which signature behaviors make a family recognizable across web, print,
    motion and copy? Require invariant/variation rules and cross-channel examples.
19. Which foundations supersede older records, and what should be invalidated
    when they change? Require versioned dependencies and stale-approval handling.
20. Who accepted the creative direction, and who authorizes final release?
    Require the two distinct authoritative decisions; neither is implied by a hash.

### Marketing

21. Which audience situation, objection and desired action does this asset address?
    Require a message-to-evidence-to-CTA map for one specific scenario.
22. What supports every material promise, testimonial and comparison? Require
    applicable evidence and consent; unsupported claims remain unverified.
23. How does the hook connect honestly to the actual value delivered? Require
    message continuity through the landing page and next action.
24. Which experiment isolates the proposed improvement? Require one declared
    variable, a comparison, an observable outcome and a stopping rule; unavailable
    traffic/conversion measurements are null, never plausible invented numbers.
25. Is publication or spend actually authorized and supported? Require current
    runtime capability and exact approval; a campaign plan is not a live executor.

## A reusable mission brief

```text
Objective: [one user/business outcome]
Scope: [authorized tenant/project and supported entry point]
Audience and situation: [evidence refs; label assumptions]
Current foundations: [artifact versions/hashes and authoritative decisions]
Hard constraints: [exact copy, approved rendering values, rights, accessibility]
Creative invariants: [what cannot change]
Variation axes: [what may change; at most three concepts]
Requested outputs: [existing artifact contracts, formats and dimensions]
Evaluation: [baseline, hard-gate assertions, task measures, human preference rubric]
Resources: [existing operation/context/retry limits; no new external effects]

First report missing or contradictory prerequisites. Reuse existing planners,
PromptIR, role contracts, guidance and verifiers. Compile only relevant context.
For each concept explain its thesis, evidence, differences and failure modes.
Validate persisted output on supported paths; distinguish NOT_RUN and BLOCKED
from passing checks. Preserve human creative-direction and release decisions.
Return the artifact refs, observed checks, unknowns and next required decision.
```

This is a brief template, not a permission grant. Do not fill absent project
foundations or approval records with generated statements.

## Repository grounding and current boundaries

Inspected baseline: `d0c78fc78167702c77054d8529d7864b8aa6812c`.
The architecture already supports these concerns; do not add a parallel planner:

- `agency/prompt_compiler.py`: evidence/claim passes, selective PromptIR,
  provider compatibility and the PROMPT_PACKAGE_READY generation firewall.
- `agency/prompt_families/`: concept ledger, invariants and declared variations;
  bounded compilation does not constitute universal originality.
- `agency/ui_ux/`: structured flows, state matrix, tokens and accessibility
  requirements; specifications do not prove rendered usability or conformance.
- Existing local rendering, AVIC, Foundry and UCPO paths provide different
  bounded execution/verification surfaces. Inspect the selected path's actual
  capabilities instead of treating every creative request as executable.
- N1–N4, Project OS, scoped role contracts and authenticated approvals retain
  ownership. No question, advisory source or role prompt can widen permissions.

The performance patch changes only guidance loading. Files are read on every
call; a bounded 32-entry LRU caches verified serialization keyed by exact bytes
and filename. Each caller receives freshly validated model instances. Sources
larger than 1 MiB bypass the cache. Changed bytes (even at the same size/mtime),
duplicate keys and invalid hashes still take the validation path. No user
project records, credentials, permissions or approvals are cached.

## Evaluation and research sources

Keep baseline/candidate content and environment matched; never expose hidden
grading answers to generation. Correctness/rights/accessibility gates come first,
then human task success and calibrated preference. "More attractive" does not
override a mandatory failure. Record latency separately for compilation, provider
calls, rendering and validation; improvements to one do not establish gains in all.

Primary sources accessed through Exa on 2026-10-29:

- [OpenAI: image evaluation](https://developers.openai.com/cookbook/examples/multimodal/image_evals):
  workflow-specific correctness, exact text, style, editing locality and human
  preference are separate evaluation dimensions. Vendor guidance is not evidence
  that AMC outputs passed those checks.
- [Microsoft Fluent 2: evaluating output quality](https://fluent2.microsoft.design/content-engineering/evaluating-output-quality):
  ground evaluations in real audiences, data boundaries, prompt sets and rubrics.
- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/): normative accessibility criteria;
  applicability and actual conformance require scoped evaluation.
- [Python 3.11 functools](https://docs.python.org/3.11/library/functools.html):
  bounded memoization and the risks of caching mutable returned objects. Cache
  design here preserves fresh caller-owned models and source-byte invalidation.

Exa discovery reviewed ten returned search results across two angles and read
four primary pages. These are methodological sources, not independent performance
studies. Wolfram verified arithmetic for the observed benchmark medians; it did
not judge creativity, source authenticity or end-to-end system quality.
