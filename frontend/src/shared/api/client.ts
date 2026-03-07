import type { ApiErrorEnvelope } from '@/shared/api/generated/backend-sdk';
import { useAuthStore } from '@/shared/store/authStore';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api';

function defaultErrorCode(statusCode: number) {
  if (statusCode === 404) return 'not_found';
  if (statusCode === 409) return 'conflict';
  if (statusCode === 422) return 'validation_error';
  if (statusCode >= 500) return 'service_unavailable';
  return 'request_invalid';
}

async function readErrorEnvelope(response: Response): Promise<ApiErrorEnvelope> {
  const requestId = response.headers.get('x-request-id');
  let text = '';
  try {
    text = await response.text();
  } catch {
    text = '';
  }

  if (text) {
    try {
      const parsed = JSON.parse(text) as ApiErrorEnvelope;
      if (parsed?.error?.code && parsed?.error?.message) {
        return parsed;
      }
    } catch {
      // fall through to generic envelope
    }
  }

  return {
    error: {
      code: defaultErrorCode(response.status),
      message: text.trim() || `Request failed with status ${response.status}`,
      retryable: response.status >= 500,
      request_id: requestId,
      details: {},
    },
  };
}

export class ApiClientError extends Error {
  code: string;
  retryable: boolean;
  requestId: string | null;
  statusCode: number;
  details: Record<string, unknown>;

  constructor(envelope: ApiErrorEnvelope, statusCode: number) {
    super(envelope.error.message);
    this.name = 'ApiClientError';
    this.code = envelope.error.code;
    this.retryable = envelope.error.retryable;
    this.requestId = envelope.error.request_id;
    this.statusCode = statusCode;
    this.details = envelope.error.details ?? {};
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown;
  skipAuth?: boolean;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers ?? {});
  headers.set('Content-Type', 'application/json');

  if (!options.skipAuth) {
    const token = useAuthStore.getState().token;
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (!response.ok) {
    const payload = await readErrorEnvelope(response);
    if (response.status === 401 && !options.skipAuth) {
      useAuthStore.getState().logout();
    }
    throw new ApiClientError(payload, response.status);
  }

  return (await response.json()) as T;
}

export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
};
