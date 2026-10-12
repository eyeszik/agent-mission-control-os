# Agency OS user guide

Open `/agency` (or the "Agency OS" link in the Mission Control header). Everything you see is checked again by
the server. The page never grants you anything your role does not already have.

**Nothing leaves this system.** Publishing, sending email, spending and deleting run only against sandbox
stand-ins. They are labelled "Sandbox" and "SIMULATED" and are never reported as delivered.

## Layout

- **Sidebar**: Overview, Clients, Projects, Missions, Creative Studio, Approvals, Deliverables, Analytics,
  Integrations, Settings. On a phone the sidebar is behind the menu button.
- **Top bar**:
  - the current project;
  - search (⌘K / Ctrl+K opens the command palette);
  - counts of running work and work that needs checking;
  - the attention bell;
  - the light/dark switch;
  - your name and role.
- **Right drawer (Inspector)**: opens when you select an action. It shows:
  - the action's state;
  - its risk class and why;
  - exactly what is bound for approval, and what changed since then;
  - the approvals;
  - the controls you may use;
  - the full evidence timeline.

## A typical engagement

1. **Create or select a client.** Clients → "Add client". Then "Link selected project" attaches the project
   chosen in the top bar.
2. **Record strategy and identity inputs.** Projects → foundation inputs (positioning, brand platform, brand
   core) → "Save inputs". Someone with an approver role then confirms the brand canon (name and colours). Your
   own role may not be able to; the page says so.
3. **Submit a brief.** Missions → describe the outcome in plain English → "Preview plan". The preview shows:
   - the deliverable;
   - the work plan in waves;
   - acceptance criteria;
   - cost;
   - any external actions the brief implies, which are never run from a brief.

   Nothing runs at this point.
4. **Launch authorized local work.** "Launch local work" runs only local production (for example a
   deterministic SVG mark). The output is stored, read back and verified, then waits for approval.
5. **Monitor progress.** The mission timeline and the top-bar counts update as work moves. The Overview lifecycle
   shows each stage as done only when its evidence exists.
6. **Review exact approvals.** Approvals lists each request with exactly what it covers: action, target, content
   hash, cost, expiry and requester. Approve or reject through a confirmation step. You can never approve your
   own request. Money and governance approvals need an owner or admin, and each needs a different person.
7. **Run a governed action (optional).** Missions → Governed actions → choose an action, edit its details,
   "Preview effect", then "Propose". Once approved, open it from Overview and choose "Run in sandbox". The
   inspector then shows "Done and checked" with a read-back, or "Outcome unknown" with "Check outcome".
8. **Request revisions.** Deliverables → "Request revision" with a note. The old approval no longer applies to a
   new version.
9. **Inspect evidence.** Every action's inspector lists its history chain (intact or broken), permits, receipts
   and read-backs. Deliverables list each version's hash, approvals, release verdict and rights record.
10. **Export verified deliverables.** Deliverables → select → "Export selected". Export re-reads the stored bytes
    first. Anything changed, unapproved or unverified is listed as excluded, with reasons. Download the manifest
    as JSON. It is signed only if the operator configured a signing key; otherwise it says "Unsigned" and why.

## Settings

- **Autonomy dial**: Observe, Draft (the default), Prepare, or Request approval. This is an upper bound on what
  may run without a person. Only an owner or admin can raise it. Publishing, sending and spending always need
  approval.
- **Incident freeze**: stops every new dispatch for the workspace or one project. Checking outcomes continues.
  Lifting needs a second owner or admin.
- **Policy simulator**: shows what a spend ceiling would block. It saves nothing.
- **Your authority**: what your role may do, and what nobody may do here.

## Status words

| You see | Means |
|---|---|
| Ready to run | Approved exactly as bound; may be run in the sandbox |
| Approval required | Waiting for a person |
| Done and checked | Run, read back and matched |
| Outcome unknown | Sent, but the result could not be confirmed. Use "Check outcome", which never re-sends |
| Needs a person | The read-back did not match or could not be read |
| Blocked | A rule refused it; the reasons are listed |
| External action disabled | A live effect; refused in this deployment |
| Tool not connected | No provider is installed for this (PROVIDER_GAP); nothing is simulated in its place |
| Not measured | No measured data exists; no number is invented |

## Accessibility

- Keyboard reachable throughout, with a skip link and visible focus.
- Status changes are announced (`role="status"`); errors use `role="alert"`.
- Light and dark themes both meet the WCAG 2.2 AA contrast pairs declared in the design tokens (tested).
- No horizontal scroll at 390 px wide.
