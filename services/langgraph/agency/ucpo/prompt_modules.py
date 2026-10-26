"""Sixteen master prompt modules, each in an expanded and a compact variant, stopping at PROMPT_PACKAGE_READY.

Modules are structured data (the fourteen fields below), not free prose, so the compact
variant is a deterministic projection of the expanded one. Every constraint, acceptance
criterion and failure carries a stable id (``C1``, ``A1``, ``F1``); ``preservation`` proves
that the compact variant keeps every one of them verbatim, so compression can drop
explanation and examples but never a rule. ``compile_module`` returns a prompt package
whose terminal state is the prompt compiler's ``PROMPT_PACKAGE_READY``; nothing here calls a
model or a provider. Running a package against a model requires a separately authorized adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from services.langgraph.agency.execution.canonical import canonical_hash
from services.langgraph.agency.prompt_compiler import GENERATION_FIREWALL

VERSION = "amc-ucpo-prompt-modules/v1"
FIELDS = ("role", "objective", "inputs", "prerequisites", "constraints", "steps", "tools", "outputs", "acceptance",
          "failures", "fallback", "escalation", "example", "requirement_mappings")
SHARED_CONSTRAINTS = (
    "Use only facts present in the inputs; mark anything else as an assumption.",
    "Never claim that a generation, build, test or approval happened unless its evidence reference is supplied.",
    "Stop at a prompt package; do not invoke providers, publish, deploy, spend or send.",
)


@dataclass(frozen=True)
class PromptModule:
    module_id: str
    name: str
    role: str
    objective: str
    inputs: tuple[str, ...]
    prerequisites: tuple[str, ...]
    constraints: tuple[str, ...]
    steps: tuple[str, ...]
    tools: tuple[str, ...]
    outputs: tuple[str, ...]
    acceptance: tuple[str, ...]
    failures: tuple[str, ...]
    fallback: str
    escalation: str
    example: str
    requirement_mappings: tuple[str, ...]


def _m(module_id, name, role, objective, inputs, prerequisites, constraints, steps, tools, outputs, acceptance, failures,
       fallback, escalation, example, maps) -> PromptModule:
    return PromptModule(module_id, name, role, objective, tuple(inputs), tuple(prerequisites),
                        tuple(constraints) + SHARED_CONSTRAINTS, tuple(steps), tuple(tools), tuple(outputs), tuple(acceptance),
                        tuple(failures), fallback, escalation, example, tuple(maps))


MODULES: tuple[PromptModule, ...] = (
    _m("01.context_intake", "Context Intake", "Intake analyst",
       "Turn a raw request into a WebsiteBrief-shaped record with every stated fact and every gap visible.",
       ["raw request text", "project id resolved by the server"], ["an authenticated principal with project access"],
       ["Quote copy exactly as given; never rewrite the client's words.", "List each missing field as a gap, not a guess."],
       ["Extract organization, audience, offering, pages and sections.", "Copy every sentence of supplied copy verbatim.",
        "List gaps and contradictions."], ["agency.intake.compile_intent"], ["WebsiteBrief draft", "gap list"],
       ["Every supplied sentence appears verbatim in the draft.", "Every required brief field is filled or listed as a gap."],
       ["Inventing a page or a claim the request did not contain.", "Dropping a sentence of supplied copy."],
       "Return the gap list only.", "Ask the operator to resolve contradictions before compiling requirements.",
       "Request: 'A site for our pottery, three pages, booking on Saturdays.' -> pages index/works/visit; gap: no copy for works.",
       ["REQUIRED_PHRASE", "SECTION_BODY"]),
    _m("02.reference_dna", "Reference DNA", "Reference analyst",
       "Extract abstract principles from references without copying any work.",
       ["reference descriptions with rights status"], ["rights status recorded for each reference"],
       ["Exclude references with unknown rights.", "Record principles (grid, rhythm, contrast), never specific compositions."],
       ["Classify each reference's rights.", "Extract principles per reference.", "Merge duplicates."], ["creative.context"],
       ["principle list with source refs"], ["No principle reproduces a specific work.", "Every principle cites its reference."],
       ["Copying a composition or a likeness.", "Using a reference with unknown rights."],
       "Use the PSEM grammar's own principles.", "Escalate rights questions to a person.",
       "Swiss editorial poster -> 'asymmetric 12-column grid, hairline division'.", ["IMAGE_RIGHTS"]),
    _m("03.psem_genome", "PSEM Genome", "Design lead",
       "Compile a PSEM CreativeGenome with the locked palette and legal pairings.",
       ["WebsiteBrief", "PSEM palette"], ["requirements compiled"],
       ["Accents only on charcoal; never accent text or graphics on paper.", "One accent per composition unless approved."],
       ["Lock the six-colour palette.", "Select the psem_editorial grammar.", "Compile DTCG tokens through the one compiler."],
       ["foundry.psem.compile_psem_genome", "agency.design_tokens"], ["CreativeGenome", "DTCG token document"],
       ["Every pairing passes psem.check_usage.", "Tokens compile deterministically."],
       ["An accent on paper.", "A second token compiler."], "Use the default PSEM genome.", "Escalate a request for a second accent.",
       "Signal red serial number on a charcoal section: 5.39:1, legal.", ["PSEM_COLOUR"]),
    _m("04.deliverable_router", "Deliverable Router", "Router",
       "Route each deliverable to a discipline and an available capability, or to a CAPABILITY_GAP.",
       ["deliverable list", "capability availability"], ["capabilities discovered on this host"],
       ["Route only to discovered capabilities.", "A gap returns its fallback specification, never a fabricated artifact."],
       ["Map the deliverable to a discipline.", "Check each route alternative.", "Return the route or the gap."],
       ["ucpo.disciplines.route"], ["route decisions"], ["Every deliverable has a route or a gap with a fallback."],
       ["Claiming a provider exists without discovery."], "Return specification-only fallbacks.",
       "Escalate a deliverable no discipline covers.", "Conceptual photography -> CAPABILITY_GAP (provider.t2i).", ["A11Y_AUTOMATED"]),
    _m("05.presentation_systems", "Presentation Systems", "Presentation designer",
       "Fill a presentation system's slots with supplied content and compile it as a site.",
       ["system id", "slot content", "images with rights"], ["slot content supplied by the operator"],
       ["Never fill a required slot with invented copy.", "Images must be procedural, owned or licensed."],
       ["Validate slots.", "Compose the board brief.", "Run the website line."], ["ucpo.presentation.compose_board"],
       ["board WebsiteBrief", "verified board site"], ["Required slots are filled from supplied content.", "The board passes browser QA."],
       ["Placeholder text.", "An image without rights."], "Compose with required slots only.", "Ask for missing slot content.",
       "Visual identity board: identity, palette, typography.", ["SECTION_HEADING", "IMAGE_ALT"]),
    _m("06.adversarial_review", "Adversarial Creative Review", "Adversarial reviewer",
       "Find where the work fails its requirements, rules or audience before a person reviews it.",
       ["requirements", "coverage report", "browser evidence"], ["browser verification has run"],
       ["Report findings with evidence references only.", "Never approve; findings feed the human review."],
       ["Read the semantic debt.", "Check failed and not-run checks.", "List risks a person should look at."],
       ["ucpo.semantic.IntentLinker"], ["findings list"], ["Every finding cites a requirement id or check."],
       ["Approving or softening a failed check."], "Return the omission list.", "Escalate blocking findings to the reviewer.",
       "Finding: req.a11y.automated FAIL on /works/ (color-contrast).", ["A11Y_AUTOMATED", "FORBIDDEN_PHRASE"]),
    _m("07.agent_roles", "Agent Roles", "Planner",
       "Assign each stage to its N3 role and artifact type.", ["stage list"], ["N3 role registry"],
       ["A role may only produce the artifact types in its contract.", "Role identity never grants publish or spend authority."],
       ["Map stages to roles.", "Check assert_role_may_produce.", "Report unmapped stages."], ["agency.kernel.roles"],
       ["stage-role table"], ["Every stage maps to a role that may produce its type."], ["Inventing a role."],
       "Leave the stage unmapped and visible.", "Escalate a stage no role may produce.",
       "build -> implementation_lead / app_build_spec.", ["NO_EXTERNAL_REQUESTS"]),
    _m("08.execution_dag", "Execution DAG", "Planner",
       "Order the stages as a dependency graph with explicit invalidation.", ["stages", "dependencies"], ["roles mapped"],
       ["A changed upstream invalidates every dependent.", "Unchanged artifacts are reused, not regenerated."],
       ["Build the graph.", "Mark the untrusted stages (build, browser).", "List what a change invalidates."],
       ["persistence depends_on edges"], ["DAG", "invalidation map"], ["The graph is acyclic.", "Untrusted stages run only in the sandbox."],
       ["A cycle.", "Running generated code outside the sandbox."], "Run stages strictly in order.", "Escalate a cycle.",
       "brief -> requirements -> site_ir -> source -> build -> browser_qa -> coverage -> release_proof.", ["RESPONSIVE_REFLOW"]),
    _m("09.ui_ux", "UI/UX", "UI/UX designer",
       "Specify pages and components that meet the accessibility contract.", ["site architecture", "tokens"], ["genome compiled"],
       ["Every interactive element is keyboard reachable with a visible focus indicator.",
        "Content reflows at 320 CSS px and at 200% text without horizontal scrolling."],
       ["Define components and states.", "Define responsive rules.", "Define focus order."], ["agency.ui_ux"],
       ["ComponentSpecs", "responsive rules"], ["Browser QA passes keyboard, reflow and zoom checks."],
       ["A hover-only control.", "A fixed-width layout."], "Use the default PSEM components.", "Escalate an inaccessible requirement.",
       "Skip link first, nav landmark labelled 'Primary'.", ["KEYBOARD_FOCUS", "RESPONSIVE_REFLOW", "TEXT_ZOOM"]),
    _m("10.3d_xr", "3D/XR", "Spatial designer",
       "Specify 3D or XR scenes and route them only to discovered renderers.", ["SceneIR"], ["capability discovery"],
       ["No XR or real-time 3D renderer is assumed.", "Provide a still and reduced-motion fallback."],
       ["Specify the scene.", "Route it.", "Record the gap if unrouted."], ["ucpo.disciplines.route", "agency.visual"],
       ["SceneIR", "route decision"], ["The scene routes to an available renderer or reports CAPABILITY_GAP."],
       ["Claiming an XR build exists."], "Scene specification only.", "Escalate a request that needs an XR runtime.",
       "Interactive 3D -> CAPABILITY_GAP (three not installed); Blender still available.", ["REDUCED_MOTION"]),
    _m("11.innovation", "Innovation", "Creative technologist",
       "Propose bounded variants that change one declared axis at a time.", ["genome", "locked invariants"], ["genome approved or draft"],
       ["Never mutate a locked invariant.", "At most four candidates and two generations."],
       ["Pick an axis.", "Propose variants.", "Record parentage."], ["foundry.variants"], ["variant records"],
       ["Each variant names its parent and the axis it changed."], ["Exceeding the resource budget."],
       "Return the parent unchanged.", "Escalate a request to change an invariant.",
       "Variant: accent amber instead of signal red on page two.", ["PSEM_COLOUR"]),
    _m("12.qa", "QA", "QA lead",
       "Plan and read the verification evidence; NOT_RUN is never PASS.", ["verification contract", "browser evidence"],
       ["a build output hash"], ["Report PASS, FAIL, NOT_RUN, INCONCLUSIVE or BLOCKED exactly as recorded.",
                                 "Automated checks do not certify WCAG conformance."],
       ["List required checks.", "Read results.", "Report gaps."], ["ucpo.qa"], ["QA summary"],
       ["Every requirement with a rendered stage has evidence or is UNRESOLVED."], ["Counting NOT_RUN as PASS."],
       "Report UNRESOLVED.", "Escalate BLOCKED checks to the operator.", "axe: PASS on 3 routes; reduced motion: PASS.",
       ["A11Y_AUTOMATED", "NO_CONSOLE_ERRORS"]),
    _m("13.failure_recovery", "Failure/Recovery", "Reliability engineer",
       "Recover interrupted work without duplicating effects.", ["durable job state", "intents"], ["the job's lease has expired"],
       ["Reconcile before retrying.", "At most three retries; identical failures dead-letter."],
       ["Read the intent.", "Adopt a committed receipt or redo a retry-safe step.", "Record the outcome."], ["agency.durable.ticks"],
       ["recovery record"], ["No step runs twice with an external effect."], ["Retrying an ambiguous effect."],
       "Dead-letter with the reason.", "Escalate a divergent reconciliation.",
       "Build interrupted after dispatch: redo (static build has no external effect).", ["NO_EXTERNAL_REQUESTS"]),
    _m("14.artifact_manifest", "Artifact Manifest", "Release manager",
       "List every artifact a release decision depends on, with exact revisions.", ["stage artifacts"], ["browser verification done"],
       ["Refer to artifacts as artifact:<id>@v<n>.", "A changed revision makes the proof stale."],
       ["Collect revisions.", "Seal the proof.", "Open an approval only if eligible."], ["ucpo.release.seal_proof"],
       ["ReleaseProof"], ["The proof names every stage revision.", "deployment is NOT_AUTHORIZED."],
       ["Reusing an approval across revisions."], "Seal a blocked proof with reasons.", "Escalate to the release manager.",
       "source: artifact:prj-1:foundry-ucpo-site-source@v3.", ["IMAGE_RIGHTS"]),
    _m("15.resource_governance", "Resource Governance", "Operator",
       "Keep work inside time, storage, retry and cost limits; report what was not measured.", ["limits", "telemetry"],
       ["limits configured"], ["Never invent a measurement; report NOT_MEASURED.", "No spend without separate approval."],
       ["Read limits.", "Compare with observed telemetry.", "Report breaches."], ["durable telemetry"], ["resource report"],
       ["Every metric names numerator, denominator, population and window."], ["Fabricated cost figures."],
       "Report NOT_MEASURED.", "Escalate any spend request.", "Build wall time 7.4 s; cost NOT_MEASURED.", ["NO_EXTERNAL_REQUESTS"]),
    _m("16.universal_creative_directive", "Universal Creative Directive", "Creative director",
       "State the whole production's intent, rules and gates in one directive.", ["all module outputs"], ["modules 01-15 compiled"],
       ["Requirements outrank taste.", "Every requirement maps to an artifact, a test, an exception or a blocker."],
       ["Summarize intent.", "List rules and gates.", "List open blockers."], ["ucpo.semantic"], ["directive"],
       ["The directive lists every open blocker."], ["Hiding a blocker."], "Return the blocker list.", "Escalate to the operator.",
       "Directive: PSEM editorial site, three pages, all copy from the brief, release blocked until approval.",
       ["SECTION_HEADING", "CTA"]),
)
_BY_ID = {m.module_id: m for m in MODULES}


def _ids(prefix: str, items: tuple[str, ...]) -> list[str]:
    return [f"{prefix}{i + 1}. {t}" for i, t in enumerate(items)]


def render(module: PromptModule, variant: Literal["expanded", "compact"]) -> str:
    c, a, f = _ids("C", module.constraints), _ids("A", module.acceptance), _ids("F", module.failures)
    if variant == "compact":
        return "\n".join([
            f"[{module.module_id} {VERSION} compact] {module.role}: {module.objective}",
            "IN: " + "; ".join(module.inputs), "OUT: " + "; ".join(module.outputs),
            "RULES:", *c, "ACCEPT:", *a, "FAIL:", *f,
            f"FALLBACK: {module.fallback}", f"ESCALATE: {module.escalation}",
            "MAPS: " + ", ".join(module.requirement_mappings), f"STOP AT {GENERATION_FIREWALL}.",
        ]) + "\n"
    return "\n".join([
        f"# {module.name} ({module.module_id}, {VERSION}, expanded)", "", f"Role: {module.role}", f"Objective: {module.objective}", "",
        "## Inputs", *(f"- {x}" for x in module.inputs), "", "## Prerequisites", *(f"- {x}" for x in module.prerequisites), "",
        "## Constraints", *c, "", "## Steps", *(f"{i + 1}) {s}" for i, s in enumerate(module.steps)), "",
        "## Tools", *(f"- {x}" for x in module.tools), "", "## Outputs", *(f"- {x}" for x in module.outputs), "",
        "## Acceptance", *a, "", "## Failures", *f, "", f"## Fallback\n{module.fallback}", "", f"## Escalation\n{module.escalation}",
        "", f"## Example\n{module.example}", "", "## Requirement mappings", ", ".join(module.requirement_mappings), "",
        f"This module stops at {GENERATION_FIREWALL}. Running it against a model needs a separately authorized adapter.",
    ]) + "\n"


def preservation(module: PromptModule) -> dict:
    """Every rule, acceptance criterion and failure of the expanded variant, verbatim in the compact one."""
    compact = render(module, "compact")
    expected = _ids("C", module.constraints) + _ids("A", module.acceptance) + _ids("F", module.failures)
    missing = [e for e in expected if e not in compact]
    return {"module_id": module.module_id, "preserved": len(expected) - len(missing), "total": len(expected), "missing": missing,
            "mappings_preserved": all(m in compact for m in module.requirement_mappings)}


def compile_module(module_id: str, variant: Literal["expanded", "compact"] = "expanded") -> dict:
    module = _BY_ID.get(module_id)
    if module is None:
        raise KeyError(f"unknown prompt module {module_id}")
    text = render(module, variant)
    check = preservation(module)
    if check["missing"] or not check["mappings_preserved"]:
        raise ValueError(f"compact variant of {module_id} lost content: {check['missing']}")
    return {"module_id": module_id, "variant": variant, "version": VERSION, "text": text,
            "content_hash": canonical_hash({"text": text}), "requirement_mappings": list(module.requirement_mappings),
            "terminal_state": GENERATION_FIREWALL, "provider_invoked": False}


def library() -> list[dict]:
    return [{"module_id": m.module_id, "name": m.name, "role": m.role, "objective": m.objective,
             "requirement_mappings": list(m.requirement_mappings), "preservation": preservation(m)} for m in MODULES]


__all__ = ["FIELDS", "MODULES", "PromptModule", "VERSION", "compile_module", "library", "preservation", "render"]
