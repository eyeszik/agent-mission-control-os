# Deterministic model check of the proposed FRRE incident FSM (design artifact, not repo code).
MAIN = ["OBSERVED","DEDUPLICATED","TRIAGED","REPRODUCTION_AUTHORIZED","REPRODUCED","DIAGNOSED","PLANNED",
        "MUTATION_AUTHORIZED","SANDBOXED","PATCHED","CANDIDATE_SEALED","VALIDATION_AUTHORIZED","VALIDATED",
        "REVIEW_READY","RELEASE_APPROVED","RELEASED","POST_RELEASE_OBSERVED","RESOLVED"]
ALT = ["BLOCKED","QUARANTINED","ESCALATED","REJECTED","RECOVERY_REQUIRED","ROLLED_BACK","NO_ACTION"]
T = {a: {b} for a, b in zip(MAIN, MAIN[1:])}
T["RESOLVED"] = set()
for s in ALT: T[s] = set()
PRE_EFFECT = MAIN[:MAIN.index("RELEASED")]
for s in PRE_EFFECT:               # anything before an external effect may stop safely
    T[s] |= {"BLOCKED","ESCALATED","REJECTED","NO_ACTION"}
for s in ["SANDBOXED","PATCHED","CANDIDATE_SEALED","VALIDATION_AUTHORIZED","VALIDATED"]:
    T[s] |= {"QUARANTINED"}        # candidate-bearing states can quarantine their candidate
T["DEDUPLICATED"] |= {"NO_ACTION"}
T["RELEASED"] |= {"RECOVERY_REQUIRED","ESCALATED"}
T["POST_RELEASE_OBSERVED"] |= {"RECOVERY_REQUIRED"}
T["RECOVERY_REQUIRED"] = {"ROLLED_BACK","ESCALATED"}
T["ROLLED_BACK"] = {"POST_RELEASE_OBSERVED"}
T["BLOCKED"] = {"TRIAGED","ESCALATED"}           # re-entry only through re-triage = fresh authorization (E01)
T["ESCALATED"] = {"TRIAGED","REJECTED","NO_ACTION"}
T["QUARANTINED"] = {"PLANNED","REJECTED","ESCALATED"}  # replan with a changed hypothesis (H)
TERMINAL = {"RESOLVED","REJECTED","NO_ACTION"}
states = set(T) | {d for v in T.values() for d in v}
def reach(src):
    seen, todo = {src}, [src]
    while todo:
        for n in T.get(todo.pop(), ()):
            if n not in seen: seen.add(n); todo.append(n)
    return seen
r = reach("OBSERVED")
print("states:", len(states), "edges:", sum(len(v) for v in T.values()))
print("unreachable:", sorted(states - r) or "none")
print("non-terminal dead ends:", sorted(s for s in states if not T.get(s) and s not in TERMINAL) or "none")
print("states that cannot reach a terminal:", sorted(s for s in states if not (reach(s) & TERMINAL)) or "none")
auth = {"REPRODUCED":"REPRODUCTION_AUTHORIZED","SANDBOXED":"MUTATION_AUTHORIZED","VALIDATED":"VALIDATION_AUTHORIZED","RELEASED":"RELEASE_APPROVED"}
bypass = [(gate, stage) for stage, gate in auth.items() for s in states if s != gate and stage in T.get(s, set())]
print("effect stages entered without their permit state:", bypass or "none")
print("RELEASED reachable only via RELEASE_APPROVED:", [s for s in states if "RELEASED" in T.get(s, set())])
