import { RelayDispatcher } from '../../src/relay/dispatcher';
import { DuplicateConflictGuard } from '../../src/relay/guards';
import { MockAdapter } from '../../src/providers/mock_adapter';
import { TransportEvidenceState, CaseContext } from '../../src/relay/types';

describe('RelayDispatcher', () => {
  let guard: DuplicateConflictGuard;
  let dispatcher: RelayDispatcher;

  beforeEach(() => {
    guard = new DuplicateConflictGuard();
    dispatcher = new RelayDispatcher(new MockAdapter(), guard);
  });

  const getValidContext = (): CaseContext => ({
    caseId: 'case-123',
    provider: 'openai',
    payload: { question: 'what is 2+2?' },
    timeoutSeconds: 5
  });

  test('successful dispatch', async () => {
    const res = await dispatcher.dispatch('slot-1', getValidContext());
    expect(res.state).toBe(TransportEvidenceState.DELIVERED);
    expect(res.result).toBeDefined();
    expect(res.providerState?.executionState).toBe('COMPLETE');
  });

  test('duplicate same-slot/same-hash is not treated as a new independent send', async () => {
    await dispatcher.dispatch('slot-1', getValidContext());
    const res2 = await dispatcher.dispatch('slot-1', getValidContext());
    expect(res2.state).toBe(TransportEvidenceState.DELIVERED);
    // Did not execute again, so no result/providerState in our mocked short-circuit
    expect(res2.result).toBeUndefined();
  });

  test('same-slot/different-hash is a conflict', async () => {
    await dispatcher.dispatch('slot-1', getValidContext());
    const ctx2 = getValidContext();
    ctx2.payload = { question: 'changed' };
    await expect(dispatcher.dispatch('slot-1', ctx2)).rejects.toThrow(/Conflict/);
  });

  test('timeout is provider-specific and does not trigger retry', async () => {
    const mockAdapter = new MockAdapter({ simulateTimeout: true });
    // Spy on mockAdapter.collect to verify it's called exactly once
    const collectSpy = jest.spyOn(mockAdapter, 'collect');

    dispatcher = new RelayDispatcher(mockAdapter, guard);
    const ctx = getValidContext();
    ctx.timeoutSeconds = 1; // Short timeout

    const res = await dispatcher.dispatch('slot-1', ctx);

    expect(res.state).toBe(TransportEvidenceState.FAILED);
    expect(collectSpy).toHaveBeenCalledTimes(1); // No retry
  });

  test('finite timeout validation: null/0/negative fails', async () => {
    const testCases = [null, 0, -5, NaN];
    for (const invalid of testCases) {
      const ctx = getValidContext();
      ctx.timeoutSeconds = invalid as number;
      await expect(dispatcher.dispatch(`slot-${invalid}`, ctx)).rejects.toThrow(/Invalid timeout value/);
    }
  });

  test('abort reaches adapter during dispatch', async () => {
    const mockAdapter = new MockAdapter({ simulateTimeout: true });
    const abortSpy = jest.spyOn(mockAdapter, 'abort');
    dispatcher = new RelayDispatcher(mockAdapter, guard);

    const abortController = new AbortController();

    const ctx = getValidContext();
    ctx.timeoutSeconds = 1; // Short timeout so test does not hang

    const promise = dispatcher.dispatch('slot-1', ctx, { abortSignal: abortController.signal });

    // Simulate abort after a short delay (during collect)
    setTimeout(() => {
      abortController.abort();
    }, 50);

    const res = await promise;
    expect(abortSpy).toHaveBeenCalled();
    // In our mock, timeout still happens and fails state, but abort was triggered.
    expect(res.state).toBe(TransportEvidenceState.FAILED);
  });

  test('stop signal prevents new dispatch', async () => {
    const abortController = new AbortController();
    abortController.abort(); // already aborted

    const res = await dispatcher.dispatch('slot-1', getValidContext(), { abortSignal: abortController.signal });
    expect(res.state).toBe(TransportEvidenceState.BLOCKED);
  });

  test('request policy override fields are rejected', async () => {
    const ctx = getValidContext();
    ctx.payload = { question: 'test', model: 'gpt-4' }; // model is forbidden to override silently

    await expect(dispatcher.dispatch('slot-1', ctx)).rejects.toThrow(/Request override fields rejected/);
  });

  test('failure in one provider does not affect another', async () => {
    const failingAdapter = new MockAdapter({ simulateErrorOnDispatch: true });
    const dispatcherFail = new RelayDispatcher(failingAdapter, new DuplicateConflictGuard());

    await expect(dispatcherFail.dispatch('slot-1', getValidContext())).rejects.toThrow(/Mock error on dispatch/);

    // Another dispatcher/adapter succeeds
    const res2 = await dispatcher.dispatch('slot-2', getValidContext());
    expect(res2.state).toBe(TransportEvidenceState.DELIVERED);
  });
});
