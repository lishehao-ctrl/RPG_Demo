// AUTO-GENERATED FILE. DO NOT EDIT.
// Source: scripts/generate_frontend_sdk.py
// OpenAPI source: contracts/openapi/backend.openapi.json
// OpenAPI sha256: 646788f0e99cdfb80571c61a73fabb064bb90d1e3c1be84972098024c7b75c35

export type ApiHttpMethod =
  | 'GET'
  | 'POST'
  | 'PUT'
  | 'PATCH'
  | 'DELETE'
  | 'OPTIONS'
  | 'HEAD'
  | 'TRACE';

export type ApiOperationMeta = {
  operationId: string;
  method: ApiHttpMethod;
  path: string;
  tags: string[];
  hasRequestBody: boolean;
  hasParameters: boolean;
  responseCodes: string[];
};

export const BACKEND_OPENAPI_SHA256 = '646788f0e99cdfb80571c61a73fabb064bb90d1e3c1be84972098024c7b75c35' as const;

export const API_OPERATIONS: ApiOperationMeta[] = [
  {
    "operationId": "admin_login_endpoint_admin_auth_login_post",
    "method": "POST",
    "path": "/admin/auth/login",
    "tags": [
      "admin-auth"
    ],
    "hasRequestBody": true,
    "hasParameters": false,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "get_http_health_endpoint_admin_observability_http_health_get",
    "method": "GET",
    "path": "/admin/observability/http-health",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "get_llm_call_health_endpoint_admin_observability_llm_call_health_get",
    "method": "GET",
    "path": "/admin/observability/llm-call-health",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "get_readiness_health_endpoint_admin_observability_readiness_health_get",
    "method": "GET",
    "path": "/admin/observability/readiness-health",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "get_runtime_errors_aggregate_endpoint_admin_observability_runtime_errors_get",
    "method": "GET",
    "path": "/admin/observability/runtime-errors",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "list_session_feedback_endpoint_admin_sessions__session_id__feedback_get",
    "method": "GET",
    "path": "/admin/sessions/{session_id}/feedback",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "create_session_feedback_endpoint_admin_sessions__session_id__feedback_post",
    "method": "POST",
    "path": "/admin/sessions/{session_id}/feedback",
    "tags": [
      "admin"
    ],
    "hasRequestBody": true,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "get_session_timeline_endpoint_admin_sessions__session_id__timeline_get",
    "method": "GET",
    "path": "/admin/sessions/{session_id}/timeline",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "list_admin_users_endpoint_admin_users_get",
    "method": "GET",
    "path": "/admin/users",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "get_admin_user_endpoint_admin_users__user_id__get",
    "method": "GET",
    "path": "/admin/users/{user_id}",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "health_health_get",
    "method": "GET",
    "path": "/health",
    "tags": [
      "health"
    ],
    "hasRequestBody": false,
    "hasParameters": false,
    "responseCodes": [
      "200"
    ]
  },
  {
    "operationId": "ready_ready_get",
    "method": "GET",
    "path": "/ready",
    "tags": [
      "health"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "create_session_endpoint_sessions_post",
    "method": "POST",
    "path": "/sessions",
    "tags": [
      "sessions"
    ],
    "hasRequestBody": true,
    "hasParameters": false,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "get_session_endpoint_sessions__session_id__get",
    "method": "GET",
    "path": "/sessions/{session_id}",
    "tags": [
      "sessions"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "step_session_endpoint_sessions__session_id__step_post",
    "method": "POST",
    "path": "/sessions/{session_id}/step",
    "tags": [
      "sessions"
    ],
    "hasRequestBody": true,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "create_story_endpoint_stories_post",
    "method": "POST",
    "path": "/stories",
    "tags": [
      "stories"
    ],
    "hasRequestBody": true,
    "hasParameters": false,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "generate_story_endpoint_stories_generate_post",
    "method": "POST",
    "path": "/stories/generate",
    "tags": [
      "stories"
    ],
    "hasRequestBody": true,
    "hasParameters": false,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "get_story_endpoint_stories__story_id__get",
    "method": "GET",
    "path": "/stories/{story_id}",
    "tags": [
      "stories"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  {
    "operationId": "publish_story_endpoint_stories__story_id__publish_post",
    "method": "POST",
    "path": "/stories/{story_id}/publish",
    "tags": [
      "stories"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  }
] as ApiOperationMeta[];

export const API_OPERATION_MAP: Record<string, ApiOperationMeta> = {
  "admin_login_endpoint_admin_auth_login_post": {
    "operationId": "admin_login_endpoint_admin_auth_login_post",
    "method": "POST",
    "path": "/admin/auth/login",
    "tags": [
      "admin-auth"
    ],
    "hasRequestBody": true,
    "hasParameters": false,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "get_http_health_endpoint_admin_observability_http_health_get": {
    "operationId": "get_http_health_endpoint_admin_observability_http_health_get",
    "method": "GET",
    "path": "/admin/observability/http-health",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "get_llm_call_health_endpoint_admin_observability_llm_call_health_get": {
    "operationId": "get_llm_call_health_endpoint_admin_observability_llm_call_health_get",
    "method": "GET",
    "path": "/admin/observability/llm-call-health",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "get_readiness_health_endpoint_admin_observability_readiness_health_get": {
    "operationId": "get_readiness_health_endpoint_admin_observability_readiness_health_get",
    "method": "GET",
    "path": "/admin/observability/readiness-health",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "get_runtime_errors_aggregate_endpoint_admin_observability_runtime_errors_get": {
    "operationId": "get_runtime_errors_aggregate_endpoint_admin_observability_runtime_errors_get",
    "method": "GET",
    "path": "/admin/observability/runtime-errors",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "list_session_feedback_endpoint_admin_sessions__session_id__feedback_get": {
    "operationId": "list_session_feedback_endpoint_admin_sessions__session_id__feedback_get",
    "method": "GET",
    "path": "/admin/sessions/{session_id}/feedback",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "create_session_feedback_endpoint_admin_sessions__session_id__feedback_post": {
    "operationId": "create_session_feedback_endpoint_admin_sessions__session_id__feedback_post",
    "method": "POST",
    "path": "/admin/sessions/{session_id}/feedback",
    "tags": [
      "admin"
    ],
    "hasRequestBody": true,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "get_session_timeline_endpoint_admin_sessions__session_id__timeline_get": {
    "operationId": "get_session_timeline_endpoint_admin_sessions__session_id__timeline_get",
    "method": "GET",
    "path": "/admin/sessions/{session_id}/timeline",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "list_admin_users_endpoint_admin_users_get": {
    "operationId": "list_admin_users_endpoint_admin_users_get",
    "method": "GET",
    "path": "/admin/users",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "get_admin_user_endpoint_admin_users__user_id__get": {
    "operationId": "get_admin_user_endpoint_admin_users__user_id__get",
    "method": "GET",
    "path": "/admin/users/{user_id}",
    "tags": [
      "admin"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "health_health_get": {
    "operationId": "health_health_get",
    "method": "GET",
    "path": "/health",
    "tags": [
      "health"
    ],
    "hasRequestBody": false,
    "hasParameters": false,
    "responseCodes": [
      "200"
    ]
  },
  "ready_ready_get": {
    "operationId": "ready_ready_get",
    "method": "GET",
    "path": "/ready",
    "tags": [
      "health"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "create_session_endpoint_sessions_post": {
    "operationId": "create_session_endpoint_sessions_post",
    "method": "POST",
    "path": "/sessions",
    "tags": [
      "sessions"
    ],
    "hasRequestBody": true,
    "hasParameters": false,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "get_session_endpoint_sessions__session_id__get": {
    "operationId": "get_session_endpoint_sessions__session_id__get",
    "method": "GET",
    "path": "/sessions/{session_id}",
    "tags": [
      "sessions"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "step_session_endpoint_sessions__session_id__step_post": {
    "operationId": "step_session_endpoint_sessions__session_id__step_post",
    "method": "POST",
    "path": "/sessions/{session_id}/step",
    "tags": [
      "sessions"
    ],
    "hasRequestBody": true,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "create_story_endpoint_stories_post": {
    "operationId": "create_story_endpoint_stories_post",
    "method": "POST",
    "path": "/stories",
    "tags": [
      "stories"
    ],
    "hasRequestBody": true,
    "hasParameters": false,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "generate_story_endpoint_stories_generate_post": {
    "operationId": "generate_story_endpoint_stories_generate_post",
    "method": "POST",
    "path": "/stories/generate",
    "tags": [
      "stories"
    ],
    "hasRequestBody": true,
    "hasParameters": false,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "get_story_endpoint_stories__story_id__get": {
    "operationId": "get_story_endpoint_stories__story_id__get",
    "method": "GET",
    "path": "/stories/{story_id}",
    "tags": [
      "stories"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  },
  "publish_story_endpoint_stories__story_id__publish_post": {
    "operationId": "publish_story_endpoint_stories__story_id__publish_post",
    "method": "POST",
    "path": "/stories/{story_id}/publish",
    "tags": [
      "stories"
    ],
    "hasRequestBody": false,
    "hasParameters": true,
    "responseCodes": [
      "200",
      "422"
    ]
  }
} as Record<string, ApiOperationMeta>;

export type ApiErrorEnvelope = {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    request_id: string | null;
    details: Record<string, unknown>;
  };
};

export function buildApiUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/$/, '')}${path}`;
}
