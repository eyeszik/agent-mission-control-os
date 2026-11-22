# Brand OS integration completion (outcome C)

Canonical detail: `docs/brand-os.md`. This file records the reconciliation state as verified in this cycle.

| Item | Verified value | How |
|---|---|---|
| SOP identities | 60 (F01–F60), in the owner-supplied order | `test_sop_brand_os_source.py::test_all_sixty_identities_match_the_supplied_list_in_order` |
| Procedures present | F01–F08 only, all `NEWLY_AUTHORED_SOP`; F09–F60 `SOURCE_UNAVAILABLE` | same file, `test_only_f01_to_f08_have_procedures_and_all_are_newly_authored_drafts` |
| Draft bytes | 8 drafts plus the README, SHA-256 pinned and unchanged in this cycle (no file under `agency/sop/data/brand_os/` was modified) | `test_every_pinned_digest_is_the_sha256_of_the_committed_draft_bytes`; `git diff --stat` shows no change there |
| Stable steps | **63** (F04 has 7; every other draft has 8), refs `F0n.Sk` with source lines | `test_the_step_inventory_is_63_with_lines_and_both_files_are_keyed_to_it` |
| AGM dispositions | **54 PARTIAL_MATCH, 9 UNRESOLVED, 0 EXACT/COMPOSITE** against catalog `9a2c30e9…df501a` | `test_mapping_counts_reconcile_and_no_step_claims_an_unevidenced_exact_match` |
| Native role binding | 54 `AGM_MODULE_BINDING` (a module-level role from `bindings.py`, not a per-step contract), 9 `MISSING` | `test_the_companion_is_advisory_and_separates_suggested_performers_from_native_bindings` |
| Adoption | API plus native approvals; requester ≠ decider; `grants_runtime_authority: false` | `test_brand_os_api.py` (9 tests) |
| Concurrent adoption | One pending approval, enforced by the database | `test_brand_os_adoption_concurrency.py` (5 tests, SQLite and PostgreSQL) |

**Not done, by design.**

- No FULL or EXACT match is claimed. The catalog has no per-task input, evidence or failure fields to evidence one.
- No F09–F60 procedure was generated.
- F01–F08 are never labelled originals.
- No real SOP was adopted in a real project: that needs an independent human approver.
