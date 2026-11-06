# Architecture

## Components

```mermaid
flowchart LR
  subgraph Browser["/agency (Next.js)"]
    UI[Agency shell: Overview · Clients · Projects · Missions · Studio · Approvals · Deliverables · Analytics · Integrations · Settings]
  end
  subgraph API["FastAPI"]
    AOS["/agency-os routes"]
    ACT["/actions routes"]
    APR["/approvals/{id}/decide (existing)"]
  end
  subgraph AgencyOS["agency/agency_os"]
    SVC[service.py: clients, lifecycle, attention, analytics, authority twin]
    MIS[missions.py: preview, launch, revisions]
    DEL[deliverables.py: vault, export manifest, verify]
  end
  subgraph Plane["agency/actions"]
    CAT[catalog.py: ActionRegistry]
    RISK[risk.py: RiskEngine R0–R6]
    BRK[broker.py: AuthorizationBroker]
    GW[gateway.py: ExecutionGateway + recovery]
    GOV[governance.py: freeze, autonomy, LIVE gate]
    EVD[evidence.py: EvidenceLedger views]
    ADP[adapters.py: sandbox fakes]
  end
  subgraph Reused["Existing owners (unchanged contracts)"]
    INT[agency/intake: compile_intent, run_mission, verify_artifact, release verdict]
    TK[trust kernel: policy decisions, recovery cases]
    PRF[persistence/proofs: permits and receipts]
    APS[approvals table + approval_authority]
    POS[Project OS: projects, artifacts, events]
  end
  DB[(migration 16: action_* + agency_clients*)]
  SBX[(action_sandbox_effects: fake provider state)]

  UI --> AOS & ACT & APR
  AOS --> SVC & MIS & DEL
  MIS --> INT
  DEL --> INT
  ACT --> GW & EVD & GOV & CAT
  GW --> CAT & RISK & BRK & GOV & ADP
  BRK --> APS
  GW --> TK & PRF & DB
  ADP --> SBX
  SVC & MIS & DEL --> POS
```

There is no LIVE edge. Adapters write only to `action_sandbox_effects`, and the gateway refuses
`Environment.LIVE` before an adapter is chosen.

## Request path

```mermaid
sequenceDiagram
  participant R as Requester
  participant G as Gateway
  participant B as Broker
  participant A as Approvers (existing decide route)
  participant P as Sandbox provider
  R->>G: POST /actions (Idempotency-Key)
  G->>G: catalogue · scope · LIVE gate · owner · secrets · args · dependencies · risk · autonomy
  G->>B: binding_hash, required approvals
  B-->>A: approvals on one anchor run (subject_hash = binding_hash)
  A->>B: decide (role + separation of duties)
  R->>G: POST /actions/{id}/dispatch
  G->>G: preflight: freeze · expiry · drift · approvals · ownership
  G->>G: reserve budget (locked) · lease · policy decision · permit
  G->>P: execute (effect key)
  G->>P: observe (independent read-back)
  alt matches binding
    G->>G: VERIFIED → COMPLETED, commit observed cost
  else timeout / unreadable
    G->>G: UNKNOWN → recovery case → RECONCILING by read-back
  end
```

## ActionRequest state machine

Every transition is a compare-and-set on `version` and appends a hash-chained row to `action_transitions`.

```mermaid
stateDiagram-v2
  [*] --> PROPOSED
  PROPOSED --> VALIDATED
  PROPOSED --> REJECTED
  VALIDATED --> PREPARED
  PREPARED --> AWAITING_APPROVAL
  PREPARED --> AUTHORIZED: within the autonomy ceiling
  AWAITING_APPROVAL --> AUTHORIZED: every bound approval matches
  AWAITING_APPROVAL --> REJECTED
  AUTHORIZED --> RESERVED: spend
  AUTHORIZED --> DISPATCHING
  RESERVED --> DISPATCHING
  DISPATCHING --> OBSERVING
  DISPATCHING --> UNKNOWN: timeout
  DISPATCHING --> FAILED
  OBSERVING --> VERIFIED
  OBSERVING --> UNKNOWN
  OBSERVING --> FAILED
  VERIFIED --> COMPLETED
  UNKNOWN --> RECONCILING
  RECONCILING --> VERIFIED
  RECONCILING --> FAILED
  RECONCILING --> NEEDS_HUMAN
  RECONCILING --> UNKNOWN
  NEEDS_HUMAN --> RECONCILING
  NEEDS_HUMAN --> FAILED
  FAILED --> AUTHORIZED: retry (≤ 3 attempts, retry-eligible only)
  COMPLETED --> [*]
```

From `PROPOSED` and `VALIDATED`, a request can also go to `BLOCKED` or `CANCELLED`. From `PREPARED`,
`AWAITING_APPROVAL`, `AUTHORIZED` and `RESERVED`, it can also go to `BLOCKED`, `CANCELLED` or `EXPIRED`.
`COMPLETED`, `REJECTED`, `BLOCKED`, `EXPIRED` and `CANCELLED` are terminal. Source: `agency/actions/fsm.py`.

## Agency lifecycle

`GET /agency-os/projects/{id}/lifecycle` derives each stage only from stored evidence:

Intake → Discovery → Strategy → Identity → Production → Review → Delivery → Distribution → Measurement → Maintenance

- **Distribution** is always `LIVE_GATED`.
- **Measurement** is `NOT_MEASURED` unless measured rows with a source exist.
- No stage is marked done because a step ran. Each stage needs its artifact, verification, approval or manifest.

## Why the gateway is never called from a graph node

LangGraph resumes an interrupted node from its start and re-executes its logic. A side effect inside a node
before an interrupt would therefore repeat. The gateway is only reachable from HTTP routes and tests;
`test_i02_no_graph_node_dispatches_through_the_gateway` scans the graph packages to enforce this.
