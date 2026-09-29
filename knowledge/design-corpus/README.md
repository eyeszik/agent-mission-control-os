# Design Corpus

This checked-in corpus supports deterministic, local reference retrieval for Agent Mission Control OS. It derives from `design-md-best-collection.zip`, whose SHA-256 is recorded in `manifest.json`.

## Safe use

The six files in `standards/` are owned internal guidance. Files in `references/` are reference-only: use transferable principles only; retain no third-party brand identity, trademarks, logos, proprietary wording, claims, or trade dress.

## Update procedure

Verify the archive with `unzip -t` and SHA-256, regenerate `manifest.json` and `catalog.json` deterministically, validate every content hash, then run the backend retrieval tests.
