import json, sys
from services.langgraph.security.pii import _redact_string, detect_pii
cases = json.load(open(sys.argv[1]))
out = []
for c in cases:
    red = _redact_string(c["text"])
    out.append({"kind": c["kind"], "positive": c["positive"], "flagged": red != c["text"] or detect_pii(c["text"]),
                "covered": bool(c["sensitive"]) and c["sensitive"] not in red, "redacted": red[:90]})
print(json.dumps(out))
