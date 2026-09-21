import { DuplicateConflictGuard, hashPayload } from '../../src/relay/guards';

describe('DuplicateConflictGuard', () => {
  let guard: DuplicateConflictGuard;

  beforeEach(() => {
    guard = new DuplicateConflictGuard();
  });

  test('hashPayload is deterministic', () => {
    const payload1 = { a: 1, b: "test" };
    const payload2 = { a: 1, b: "test" };
    const payload3 = { a: 2, b: "test" };

    expect(hashPayload(payload1)).toEqual(hashPayload(payload2));
    expect(hashPayload(payload1)).not.toEqual(hashPayload(payload3));
  });

  test('allows new slot', () => {
    const isDup = guard.checkIntent('slot-1', 'hash-1');
    expect(isDup).toBe(false);
  });

  test('recognizes same slot + same hash as duplicate', () => {
    guard.checkIntent('slot-1', 'hash-1');
    const isDup = guard.checkIntent('slot-1', 'hash-1');
    expect(isDup).toBe(true);
  });

  test('throws conflict error for same slot + different hash', () => {
    guard.checkIntent('slot-1', 'hash-1');
    expect(() => guard.checkIntent('slot-1', 'hash-2')).toThrow(/Conflict: slot slot-1 was already dispatched/);
  });
});
