import { describe, expect, it } from 'vitest';
import { ApiClientError } from '@/shared/api/client';
import { formatApiError } from '@/shared/lib/apiErrorPresentation';

function makeApiError(payload: {
  code: string;
  message: string;
  request_id?: string | null;
  retryable?: boolean;
  details?: Record<string, unknown>;
}, statusCode: number) {
  return new ApiClientError(
    {
      error: {
        code: payload.code,
        message: payload.message,
        retryable: payload.retryable ?? false,
        request_id: payload.request_id ?? 'req-test',
        details: payload.details ?? {},
      },
    },
    statusCode,
  );
}

describe('formatApiError', () => {
  it('maps login invalid credentials to human copy', () => {
    const error = makeApiError({ code: 'invalid_credentials', message: 'invalid credentials' }, 401);
    const result = formatApiError(error, 'login');
    expect(result.title).toBe('邮箱或密码不正确');
    expect(result.message).toContain('请确认登录信息');
    expect(result.technical.code).toBe('invalid_credentials');
  });

  it('maps missing draft target to refresh guidance', () => {
    const error = makeApiError({ code: 'draft_target_not_found', message: 'scene not found' }, 404);
    const result = formatApiError(error, 'author-draft-save');
    expect(result.title).toBe('编辑目标已经变化');
    expect(result.message).toContain('不在最新草稿');
  });

  it('translates npc validation errors into ui language', () => {
    const error = makeApiError(
      {
        code: 'validation_error',
        message: 'draft patch invalid',
        details: {
          errors: [{ loc: ['npc_profiles', 0, 'red_line'], msg: 'String should have at least 1 character' }],
        },
      },
      422,
    );
    const result = formatApiError(error, 'author-draft-save');
    expect(result.title).toBe('输入内容暂时不符合要求');
    expect(result.message).toBe('NPC red line 不能为空');
  });

  it('falls back to loc path when no friendly mapping exists', () => {
    const error = makeApiError(
      {
        code: 'validation_error',
        message: 'draft patch invalid',
        details: {
          errors: [{ loc: ['changes', 0, 'value'], msg: 'String should have at least 1 character' }],
        },
      },
      422,
    );
    const result = formatApiError(error, 'author-draft-save');
    expect(result.message).toContain('changes -> 0 -> value');
  });

  it('maps service unavailable to human retry guidance', () => {
    const error = makeApiError({ code: 'service_unavailable', message: 'backend exploded', retryable: true }, 503);
    const result = formatApiError(error, 'play-session-step');
    expect(result.title).toBe('服务暂时不可用');
    expect(result.suggestions[0]).toContain('request id');
  });
});
