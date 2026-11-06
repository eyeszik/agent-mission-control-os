# Production SLO Contract

Status: baseline required before numeric objectives are approved.

This repository defines the measurement contract but does not fabricate
production targets before a real deployment has enough telemetry to establish a
baseline.

| Objective | Target | Measurement source | Current status |
| --- | --- | --- | --- |
| Availability | UNSET | deployed request/service telemetry | GAP_NO_BASELINE |
| Latency | UNSET | deployed request duration telemetry | GAP_NO_BASELINE |
| Error rate | UNSET | deployed HTTP/runtime error telemetry | GAP_NO_BASELINE |
| Recovery | UNSET | recovery-case and remediation telemetry | GAP_NO_BASELINE |

## Promotion rule

A row may move to `SOURCE_ATTACHED` only when the exact deployed revision,
measurement window, query/source, owner, and numeric target are recorded.
Repository tests and local E2E are evidence of software behavior, not a
production SLO baseline.

## Required telemetry

The production service must provide inspectable logs, metrics, and traces (or
an equivalent evidence set) with a stable service identity, retention policy,
alert ownership, and revision correlation. No specific telemetry vendor is
required.

## Failure behavior

Missing telemetry or a missing baseline does not invent a target. The
`amc-agency-operations/v1` package keeps these objectives at
`GAP_NO_BASELINE`, and production acceptance must keep the external evidence
dependency visible.
