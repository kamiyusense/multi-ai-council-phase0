export enum TransportEvidenceState {
  PREPARED_RESERVED = 'prepared/reserved',
  PREFLIGHT_OK = 'preflight-ok',
  SENT = 'sent',
  BACKEND_COMPLETED = 'backend-completed',
  READBACK_VERIFIED = 'readback-verified',
  DELIVERED = 'delivered',
  BLOCKED = 'blocked',
  FAILED = 'failed',
  UNKNOWN = 'unknown',
}

export interface CaseContext {
  caseId: string;
  payload: any;
  provider: string;
  timeoutSeconds?: number | null;
  // Overrides shouldn't be here silently, dispatcher should block arbitrary fields.
}

export interface PreparedContext {
  caseId: string;
  provider: string;
  serializedPayload: string;
  timeoutSeconds?: number | null;
}

export interface PreflightResult {
  ok: boolean;
  reason?: string;
}

export interface ProcessHandle {
  processId: string;
  provider: string;
}

export interface RawResult {
  stdout: string;
  stderr: string;
  exitCode: number;
  rawResponse: string;
}

export interface AbortResult {
  aborted: boolean;
  reason?: string;
}

export interface ProviderState {
  executionState: string;
  participationState?: string;
  answerState?: string;
  capabilityState: string;
}

export interface ProviderAdapter {
  prepare(caseContext: CaseContext): Promise<PreparedContext>;
  preflight(preparedContext: PreparedContext): Promise<PreflightResult>;
  dispatch(preparedContext: PreparedContext): Promise<ProcessHandle>;
  collect(processHandle: ProcessHandle): Promise<RawResult>;
  abort(processHandle: ProcessHandle): Promise<AbortResult>;
  classify(rawResult: RawResult): Promise<ProviderState>;
}
