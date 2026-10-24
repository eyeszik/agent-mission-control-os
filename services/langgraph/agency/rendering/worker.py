"""Trusted queue driver; the child render process has no DB credentials.

Run this control-plane process separately from the interaction API:
python -m services.langgraph.agency.rendering.worker --job JOB_ID
An external process supervisor can invoke --once periodically. No hidden loop.
"""
import argparse
import json
from services.langgraph.agency.durable.ticks import run_tick
from .service import KIND, RenderHandler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if not args.job:
        if not args.once:
            parser.error('--job JOB_ID or --once is required')
        from services.langgraph.persistence.database import transaction, table
        from services.langgraph.persistence.durable_runs import iso
        from datetime import datetime, timezone
        with transaction() as db:
            row = db.execute(f"SELECT job_id FROM {table('durable_jobs')} WHERE kind = ? AND ((state IN ('SCHEDULED','RETRY_PENDING') AND next_due_at <= ?) OR (lease_expires_at IS NOT NULL AND lease_expires_at <= ? AND lease_owner IS NOT NULL)) ORDER BY next_due_at, job_id LIMIT 1", (KIND, iso(datetime.now(timezone.utc)), iso(datetime.now(timezone.utc)))).fetchone()
        if row is None:
            print(json.dumps({'outcome': 'NO_WORK'}))
            return
        args.job = row['job_id']
    report = run_tick(worker_id='creative-local-driver', handlers={KIND: RenderHandler()}, job_id=args.job)
    print(json.dumps({'job_id': report.job_id, 'outcome': report.outcome, 'state': report.final_state, 'reasons': report.reasons}))


if __name__ == '__main__':
    main()
