import {
  ProviderAdapter,
  CaseContext,
  PreparedContext,
  PreflightResult,
  ProcessHandle,
  RawResult,
  AbortResult,
  ProviderState
} from '../relay/types';

export interface MockAdapterConfig {
  simulatePreflightFail?: boolean;
  simulateTimeout?: boolean;
  simulateErrorOnDispatch?: boolean;
  simulateErrorOnCollect?: boolean;
}

/**
 * A mock adapter that simulates provider operations without running live processes.
 * Used for testing the relay dispatch logic, duplicate guards, and failure isolation.
 */
export class MockAdapter implements ProviderAdapter {
  constructor(private readonly config: MockAdapterConfig = {}) {}

  async prepare(caseContext: CaseContext): Promise<PreparedContext> {
    return {
      caseId: caseContext.caseId,
      provider: caseContext.provider,
      serializedPayload: JSON.stringify(caseContext.payload),
      timeoutSeconds: caseContext.timeoutSeconds ?? null
    };
  }

  async preflight(preparedContext: PreparedContext): Promise<PreflightResult> {
    if (this.config.simulatePreflightFail) {
      return { ok: false, reason: 'Mock preflight fail' };
    }
    return { ok: true };
  }

  async dispatch(preparedContext: PreparedContext): Promise<ProcessHandle> {
    if (this.config.simulateErrorOnDispatch) {
      throw new Error('Mock error on dispatch');
    }
    return {
      processId: `mock-proc-${preparedContext.caseId}`,
      provider: preparedContext.provider
    };
  }

  async collect(processHandle: ProcessHandle): Promise<RawResult> {
    if (this.config.simulateErrorOnCollect) {
      throw new Error('Mock error on collect');
    }

    if (this.config.simulateTimeout) {
      // Simulate hanging forever so dispatcher times out
      return new Promise(() => {});
    }

    return {
      stdout: 'mock stdout',
      stderr: '',
      exitCode: 0,
      rawResponse: '{"answer_state": "ANSWER", "conclusion_code": "OK"}'
    };
  }

  async abort(processHandle: ProcessHandle): Promise<AbortResult> {
    return { aborted: true, reason: 'Mock abort called' };
  }

  async classify(rawResult: RawResult): Promise<ProviderState> {
    return {
      executionState: 'COMPLETE',
      participationState: 'PARTICIPANT',
      capabilityState: 'CONFIRMED'
    };
  }
}
