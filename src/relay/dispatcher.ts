import { ProviderAdapter, CaseContext, TransportEvidenceState, RawResult, ProviderState } from './types';
import { DuplicateConflictGuard, hashPayload } from './guards';

export interface DispatcherOptions {
  abortSignal?: AbortSignal;
}

export class RelayDispatcher {
  constructor(
    private readonly adapter: ProviderAdapter,
    private readonly guard: DuplicateConflictGuard
  ) {}

  public async dispatch(
    slotId: string,
    context: CaseContext,
    options?: DispatcherOptions
  ): Promise<{ state: TransportEvidenceState; result?: RawResult; providerState?: ProviderState }> {

    // 4.6 Execution flags/evidence timing
    // Ensure flags are only set after actions occur.

    // 4.8 Request override protection
    if (this.hasOverrideFields(context.payload)) {
       throw new Error('Request override fields rejected.');
    }

    // Hash the context payload
    const payloadHash = hashPayload(context.payload);

    // 4.1 Check conflict guards
    const isDuplicate = this.guard.checkIntent(slotId, payloadHash);

    if (isDuplicate) {
      // In live mode, this might return the existing receipt.
      return { state: TransportEvidenceState.DELIVERED };
    }

    let currentState = TransportEvidenceState.PREPARED_RESERVED;

    try {
      // 1. Prepare
      const prepared = await this.adapter.prepare(context);

      // 2. Preflight
      const preflight = await this.adapter.preflight(prepared);
      if (!preflight.ok) {
        return { state: TransportEvidenceState.BLOCKED };
      }
      currentState = TransportEvidenceState.PREFLIGHT_OK;

      // 4.9 Timeout logic
      let timeoutSeconds = context.timeoutSeconds;
      if (timeoutSeconds === undefined || timeoutSeconds === null || timeoutSeconds <= 0 || isNaN(timeoutSeconds)) {
        throw new Error('Invalid timeout value. Positive finite timeout is required.');
      }

      // Check abort before dispatching
      if (options?.abortSignal?.aborted) {
        return { state: TransportEvidenceState.BLOCKED };
      }

      // 3. Dispatch
      const processHandle = await this.adapter.dispatch(prepared);
      currentState = TransportEvidenceState.SENT;

      // Handle Abort Signal after dispatch starts
      options?.abortSignal?.addEventListener('abort', () => {
         this.adapter.abort(processHandle).catch(console.error);
      });

      // 4. Collect with Timeout. We do NOT retry or fallback.
      const rawResult = await this.runWithTimeout(
         this.adapter.collect(processHandle),
         timeoutSeconds
      );

      currentState = TransportEvidenceState.BACKEND_COMPLETED;

      // 5. Classify
      const providerState = await this.adapter.classify(rawResult);

      return {
        state: TransportEvidenceState.DELIVERED,
        result: rawResult,
        providerState
      };

    } catch (err: any) {
      if (err.message === 'Timeout') {
        // No automatic retry or fallback on timeout
        return { state: TransportEvidenceState.FAILED };
      }
      throw err;
    }
  }

  private hasOverrideFields(payload: any): boolean {
    if (!payload) return false;
    // Disallow overriding certain policy fields
    const blockedFields = ['model', 'modelProvider', 'serviceTier', 'approvalPolicy', 'sandbox', 'cwd', 'billingRoute'];
    for (const field of blockedFields) {
      if (payload.hasOwnProperty && payload.hasOwnProperty(field)) {
        return true;
      }
    }
    return false;
  }

  private runWithTimeout<T>(promise: Promise<T>, timeoutSeconds: number): Promise<T> {
    let timeoutId: NodeJS.Timeout;
    const timeoutPromise = new Promise<T>((_, reject) => {
      timeoutId = setTimeout(() => {
        reject(new Error('Timeout'));
      }, timeoutSeconds * 1000);
    });

    return Promise.race([
      promise.finally(() => clearTimeout(timeoutId)),
      timeoutPromise
    ]);
  }
}
