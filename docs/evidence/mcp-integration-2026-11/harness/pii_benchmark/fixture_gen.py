"""Build the C14 PII/secret benchmark fixture at run time (seeded, deterministic).

The fixture is generated rather than committed because several cases are random strings shaped like live
credentials (Stripe, Slack, GitHub, ...). They are synthetic, but secret-shaped literals do not belong in git,
and GitHub push protection rightly refuses them. Usage: ``python fixture_gen.py OUT.json``.
"""

import json
import random
import string
import sys

R = random.Random(7)


def rnd(n, alphabet=string.ascii_letters + string.digits):
    return "".join(R.choice(alphabet) for _ in range(n))


def build() -> list[dict]:
    p = [  # (kind, text, sensitive substring); None means derived below. Values are documented examples or random.
        ("email", "Contact jane.doe@example.org for access.", "jane.doe@example.org"),
        ("phone_us", "Call 415-555-0132 tomorrow.", "415-555-0132"),
        ("phone_intl_uk", "UK office: +44 20 7946 0958.", "+44 20 7946 0958"),
        ("phone_intl_in", "India desk +91 98765 43210 is open.", "+91 98765 43210"),
        ("ssn", "SSN on file: 123-45-6789.", "123-45-6789"),
        ("card_visa_test", "Card 4111 1111 1111 1111 exp 12/29.", "4111 1111 1111 1111"),
        ("iban", "Pay to GB82 WEST 1234 5698 7654 32 today.", "GB82 WEST 1234 5698 7654 32"),
        ("uk_nino", "NI number QQ 12 34 56 C recorded.", "QQ 12 34 56 C"),
        ("ipv4", "Origin 203.0.113.42 was blocked.", "203.0.113.42"),
        ("aws_key", "aws_access_key_id = AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ("github_pat", "token ghp_" + rnd(36) + " leaked", None),
        ("stripe_live", "STRIPE=sk_" + "live_" + rnd(24), None),
        ("openai_proj", "key sk-proj-" + rnd(40), None),
        ("google_api", "maps key AIza" + rnd(35, string.ascii_letters + string.digits + "_-"), None),
        ("slack_bot", "slack xox" + "b-" + rnd(11, string.digits) + "-" + rnd(13, string.digits) + "-" + rnd(24), None),
        ("jwt", "auth eyJhbGciOiJIUzI1NiJ9." + rnd(30) + "." + rnd(43, string.ascii_letters + string.digits + "_-"),
         None),
        ("bearer", "Authorization: Bearer " + rnd(40), None),
        ("private_key", "-----BEGIN RSA PRIVATE KEY-----\nMIIE" + rnd(60) + "\n-----END RSA PRIVATE KEY-----",
         "-----BEGIN RSA PRIVATE KEY-----"),
        ("db_url_password", "DATABASE_URL=postgres://app:" + rnd(16) + "@db.internal:5432/amc", None),
    ]
    derive = {"github_pat": lambda t: t.split(" ")[1], "bearer": lambda t: t.split(" ")[-1],
              "db_url_password": lambda t: t.split(":")[2].split("@")[0], "stripe_live": lambda t: t.split("=")[1]}
    cases = [{"kind": k, "text": t, "sensitive": s if s is not None else derive.get(k, lambda x: x.split(" ")[-1])(t),
              "positive": True} for k, t, s in p]
    benign = ["Order #48213 shipped on 2026-11-24 for Rs 4,999.", "ROAS was 4.2x at a 40% margin; CAC payback 2.5 months.",
              "Release v1.2.3 and build 2026.11.24.1 are ready.", "ISBN 978-3-16-148410-0 is the second edition.",
              "Commit 7ac18f8af1079cdff91dd11f672ba023100b4b06 merged.", "Run id 45490073702 finished in 1080 seconds.",
              "UUID 3f2504e0-4f89-11d3-9a0c-0305e82c3301 identifies the mission.", "Meeting at 10:30 in room 4B, floor 12.",
              "Budget 1,250,000 split across 12 channels.", "The SKU 8901234567890 is out of stock."]
    return cases + [{"kind": f"benign_{i}", "text": t, "sensitive": None, "positive": False} for i, t in enumerate(benign)]


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        json.dump(build(), handle, indent=1)
