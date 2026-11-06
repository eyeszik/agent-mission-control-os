import type { Database } from '../pool.js';
import { AislError } from '../../lib/errors.js';

export type CheckoutClaim =
  | { kind: 'acquired' }
  | { kind: 'replay'; body: unknown }
  | { kind: 'in_flight' }
  | { kind: 'mismatch' };

/**
 * Checkout replay protection.
 *
 * A shared payment token is scoped to a single transaction amount; charging it
 * twice because an agent retried a timed-out HTTP call is the most expensive
 * failure this gateway can have. The key is claimed before any external
 * mutation and only completed once the order exists.
 */
export class CheckoutIdempotencyRepository {
  constructor(private readonly db: Database) {}

  async claim(key: string, requestSha256: string): Promise<CheckoutClaim> {
    const inserted = await this.db.query(
      `INSERT INTO checkout_idempotency (idempotency_key, request_sha256, state)
       VALUES ($1, $2, 'IN_FLIGHT')
       ON CONFLICT (idempotency_key) DO NOTHING`,
      [key, requestSha256],
    );
    if (inserted.rowCount > 0) {
      return { kind: 'acquired' };
    }

    const { rows } = await this.db.query<{
      request_sha256: string;
      state: string;
      response_body: unknown;
    }>(`SELECT request_sha256, state, response_body FROM checkout_idempotency WHERE idempotency_key = $1`, [key]);

    const row = rows[0];
    if (!row) {
      // The row vanished between the conflict and the read (a release raced us).
      throw AislError.conflict('idempotency_race', 'idempotency key state changed during claim; retry the request');
    }
    if (row.request_sha256 !== requestSha256) {
      return { kind: 'mismatch' };
    }
    if (row.state === 'COMPLETED') {
      return { kind: 'replay', body: row.response_body };
    }
    return { kind: 'in_flight' };
  }

  async complete(key: string, conversionId: string, body: unknown): Promise<void> {
    await this.db.query(
      `UPDATE checkout_idempotency
          SET state = 'COMPLETED', conversion_id = $2, response_body = $3, completed_at = NOW()
        WHERE idempotency_key = $1`,
      [key, conversionId, JSON.stringify(body)],
    );
  }

  /** Drop an unfinished claim so a corrected retry is not locked out forever. */
  async release(key: string): Promise<void> {
    await this.db.query(`DELETE FROM checkout_idempotency WHERE idempotency_key = $1 AND state = 'IN_FLIGHT'`, [key]);
  }
}
