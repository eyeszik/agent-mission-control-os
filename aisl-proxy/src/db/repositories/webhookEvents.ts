import type { Database } from '../pool.js';

export type WebhookOutcome =
  | 'SETTLED'
  | 'REVERSED'
  | 'IGNORED_UNHANDLED_TYPE'
  | 'IGNORED_NO_MATCHING_CONVERSION'
  | 'IGNORED_ALREADY_REFUNDED';

export class WebhookEventRepository {
  constructor(private readonly db: Database) {}

  /**
   * Durable dedupe backstop.
   *
   * Redis SETNX is the hot path; this insert is what keeps the guarantee if
   * Redis is flushed, fails over, or its key expires before a retry storm
   * ends. Returns false when the event was already recorded.
   */
  async claim(input: {
    eventId: string;
    eventType: string;
    payloadSha256: string;
  }): Promise<boolean> {
    const { rowCount } = await this.db.query(
      `INSERT INTO webhook_events (event_id, event_type, payload_sha256, outcome)
       VALUES ($1, $2, $3, 'IN_FLIGHT')
       ON CONFLICT (event_id) DO NOTHING`,
      [input.eventId, input.eventType, input.payloadSha256],
    );
    return rowCount > 0;
  }

  async complete(eventId: string, outcome: WebhookOutcome, conversionId: string | null): Promise<void> {
    await this.db.query(`UPDATE webhook_events SET outcome = $2, conversion_id = $3 WHERE event_id = $1`, [
      eventId,
      outcome,
      conversionId,
    ]);
  }

  /** Release the claim so a genuine retry of a failed handler can run again. */
  async release(eventId: string): Promise<void> {
    await this.db.query(`DELETE FROM webhook_events WHERE event_id = $1 AND outcome = 'IN_FLIGHT'`, [eventId]);
  }

  async find(eventId: string): Promise<{ eventId: string; outcome: string; conversionId: string | null } | null> {
    const { rows } = await this.db.query<{ event_id: string; outcome: string; conversion_id: string | null }>(
      `SELECT event_id, outcome, conversion_id FROM webhook_events WHERE event_id = $1`,
      [eventId],
    );
    const row = rows[0];
    return row ? { eventId: row.event_id, outcome: row.outcome, conversionId: row.conversion_id } : null;
  }
}
