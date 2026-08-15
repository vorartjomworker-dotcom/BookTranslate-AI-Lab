export type ApiErrorEnvelope = {
  code?: string;
  message?: string;
  details?: unknown;
  request_id?: string;
};
