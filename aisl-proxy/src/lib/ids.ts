import { v7 as uuidv7, validate as uuidValidate, version as uuidVersion } from 'uuid';

/**
 * Click identifiers are UUIDv7: time-ordered, so the primary key on
 * `agent_intents` stays append-friendly under load and the creation instant is
 * recoverable from the identifier itself.
 */
export function newClickId(): string {
  return uuidv7();
}

export function isUuidV7(value: string): boolean {
  return uuidValidate(value) && uuidVersion(value) === 7;
}

export function isUuid(value: string): boolean {
  return uuidValidate(value);
}

/** Extract the embedded millisecond timestamp from a UUIDv7. */
export function uuidV7Timestamp(value: string): Date {
  if (!isUuidV7(value)) {
    throw new Error(`not a UUIDv7: ${value}`);
  }
  const hex = value.replace(/-/g, '').slice(0, 12);
  return new Date(Number.parseInt(hex, 16));
}
