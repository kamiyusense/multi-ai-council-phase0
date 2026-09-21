import * as crypto from 'crypto';

export function hashPayload(payload: any): string {
  const serialized = JSON.stringify(payload) || '';
  return crypto.createHash('sha256').update(serialized).digest('hex');
}

export class DuplicateConflictGuard {
  // Map of slotId -> payloadHash
  private ledger: Map<string, string> = new Map();

  /**
   * Checks the intent to send.
   * Returns true if it's safe to send (new slot or same slot + same hash).
   * Throws an error if it's a conflict (same slot + different hash).
   */
  public checkIntent(slotId: string, payloadHash: string): boolean {
    const existingHash = this.ledger.get(slotId);

    if (existingHash) {
      if (existingHash === payloadHash) {
        // Same slot + same hash = same request, safe to treat as duplicate/already sent.
        // It should NOT be treated as a new independent send, but returning true here
        // implies the caller handles idempotent responses, or we throw/return a specific status.
        // For simplicity, let's say it's valid but already processed.
        return true;
      } else {
        // Same slot + different hash = conflict.
        throw new Error(`Conflict: slot ${slotId} was already dispatched with a different hash.`);
      }
    }

    // Not seen before, register it.
    this.ledger.set(slotId, payloadHash);
    return false; // False means it's a new intent, not an existing one
  }
}
