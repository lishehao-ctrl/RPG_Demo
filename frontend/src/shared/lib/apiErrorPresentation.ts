import { ApiClientError } from '@/shared/api/client';

export type ErrorPresentationContext =
  | 'generic'
  | 'login'
  | 'author-stories-load'
  | 'author-generate'
  | 'author-draft-load'
  | 'author-draft-save'
  | 'author-publish'
  | 'play-library-load'
  | 'play-create-session'
  | 'play-session-load'
  | 'play-session-step';

export type FriendlyErrorViewModel = {
  title: string;
  message: string;
  severity: 'error' | 'warning';
  suggestions: string[];
  technical: {
    code: string | null;
    requestId: string | null;
    statusCode: number | null;
    retryable: boolean | null;
    details: Record<string, unknown>;
  };
};

function firstValidationMessage(details: Record<string, unknown>): string | null {
  const rawErrors = details.errors;
  if (!Array.isArray(rawErrors) || rawErrors.length === 0) {
    return null;
  }
  const first = rawErrors[0];
  if (typeof first === 'string' && first.trim()) {
    return first.trim();
  }
  if (first && typeof first === 'object') {
    const message = typeof (first as { msg?: unknown }).msg === 'string' ? (first as { msg: string }).msg : '';
    const location = Array.isArray((first as { loc?: unknown }).loc)
      ? (first as { loc: unknown[] }).loc.map((part) => String(part)).join(' -> ')
      : '';
    if (message && location) {
      return `${location}: ${message}`;
    }
    if (message) {
      return message;
    }
  }
  return null;
}

function contextFallback(context: ErrorPresentationContext): Pick<FriendlyErrorViewModel, 'title' | 'message' | 'suggestions'> {
  switch (context) {
    case 'login':
      return {
        title: '无法登录',
        message: '请检查邮箱和密码后重试。',
        suggestions: ['确认账号密码无误，再重新提交。'],
      };
    case 'author-stories-load':
      return {
        title: '故事列表没有加载出来',
        message: '暂时无法读取 Author story index。',
        suggestions: ['刷新故事列表，或稍后再试。'],
      };
    case 'author-generate':
      return {
        title: '故事生成没有完成',
        message: '这次 draft 生成没有成功返回。',
        suggestions: ['检查 prompt 或 seed 是否过长、过空，必要时简化后再试。'],
      };
    case 'author-draft-load':
      return {
        title: '草稿详情没有加载出来',
        message: '当前 draft 详情暂时不可读。',
        suggestions: ['返回故事列表刷新后重试。'],
      };
    case 'author-draft-save':
      return {
        title: '保存草稿失败',
        message: '这次轻量编辑没有成功写回后端。',
        suggestions: ['检查当前修改内容，再点击保存。'],
      };
    case 'author-publish':
      return {
        title: '发布失败',
        message: '当前草稿还不能顺利发布到 Play。',
        suggestions: ['先处理 review 中的 blocking 问题，再重新发布。'],
      };
    case 'play-library-load':
      return {
        title: '可游玩的故事库没有加载出来',
        message: 'Play library 现在暂时不可用。',
        suggestions: ['稍后刷新，或回 Author 确认是否已有已发布故事。'],
      };
    case 'play-create-session':
      return {
        title: '创建游玩会话失败',
        message: '这条已发布故事暂时无法启动 session。',
        suggestions: ['返回故事库重试，或稍后再试。'],
      };
    case 'play-session-load':
      return {
        title: '会话没有加载出来',
        message: '当前 session 的运行状态暂时不可读。',
        suggestions: ['刷新会话页面后再试。'],
      };
    case 'play-session-step':
      return {
        title: '这一回合没有成功提交',
        message: '系统没有成功处理这次输入。',
        suggestions: ['可以刷新当前 session，或者改用 free input 再试一次。'],
      };
    default:
      return {
        title: '操作没有成功完成',
        message: '请稍后重试。',
        suggestions: [],
      };
  }
}

export function formatApiError(error: unknown, context: ErrorPresentationContext = 'generic'): FriendlyErrorViewModel {
  const fallback = contextFallback(context);

  if (!(error instanceof ApiClientError)) {
    return {
      title: fallback.title,
      message: error instanceof Error && error.message ? error.message : fallback.message,
      severity: 'error',
      suggestions: fallback.suggestions,
      technical: {
        code: null,
        requestId: null,
        statusCode: null,
        retryable: null,
        details: {},
      },
    };
  }

  const code = error.code;
  const details = error.details ?? {};
  const validationMessage = firstValidationMessage(details);

  if (context === 'login' && code === 'invalid_credentials') {
    return {
      title: '邮箱或密码不正确',
      message: '请确认登录信息后重新尝试。',
      severity: 'warning',
      suggestions: ['如果你刚改过管理员凭证，请确认后端已经重启并加载了最新配置。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (error.statusCode === 401) {
    return {
      title: '登录已失效',
      message: '请重新登录后再继续操作。',
      severity: 'warning',
      suggestions: ['重新进入登录页，完成认证后再试。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (error.statusCode === 403) {
    return {
      title: '当前账号没有权限',
      message: '这个操作需要更高权限或当前账号不可用。',
      severity: 'warning',
      suggestions: ['确认当前账号仍然有效，或改用有权限的管理员账号。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (code === 'draft_target_not_found') {
    return {
      title: '编辑目标已经变化',
      message: '你修改的 beat、scene 或 NPC 现在已经不在最新草稿里了。',
      severity: 'warning',
      suggestions: ['刷新当前草稿，再重新应用这次修改。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (code === 'not_found' || error.statusCode === 404) {
    return {
      title: '内容不存在',
      message: '你要访问的内容可能已经被重置、删除，或还没有生成出来。',
      severity: 'warning',
      suggestions: ['返回上一页刷新后再试。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (code === 'conflict' || error.statusCode === 409) {
    return {
      title: '状态冲突',
      message: '当前内容已经变化，你的这次操作和最新状态不一致。',
      severity: 'warning',
      suggestions: ['刷新页面获取最新内容后再试。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (code === 'prompt_compile_failed') {
    return {
      title: '提示词编译失败',
      message: '这次故事生成没有成功把输入整理成可生成的结构。',
      severity: 'warning',
      suggestions: ['简化 prompt，减少复合要求，或改用 seed 再试一次。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (code.startsWith('generation_failed')) {
    return {
      title: '故事生成没有完成',
      message: 'LLM 这次没有稳定地产出可用草稿。',
      severity: 'warning',
      suggestions: ['稍微收窄题材描述，或者过一会儿再试。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (code === 'validation_error' || error.statusCode === 422) {
    return {
      title: context === 'author-publish' ? '草稿还不能发布' : '输入内容暂时不符合要求',
      message:
        validationMessage ||
        (context === 'author-draft-save'
          ? '保存失败，当前修改不符合草稿结构要求。'
          : '请求格式或当前数据状态不符合接口要求。'),
      severity: 'warning',
      suggestions:
        context === 'author-publish'
          ? ['先处理 Review Signals 中的 blocking 问题，再重新发布。']
          : fallback.suggestions,
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  if (code === 'service_unavailable' || error.statusCode >= 500) {
    return {
      title: '服务暂时不可用',
      message: '后端这次没有稳定返回结果，请稍后再试。',
      severity: 'error',
      suggestions: ['如果问题持续出现，请带上 request id 检查后端日志。'],
      technical: {
        code,
        requestId: error.requestId,
        statusCode: error.statusCode,
        retryable: error.retryable,
        details,
      },
    };
  }

  return {
    title: fallback.title,
    message: error.message || fallback.message,
    severity: error.statusCode >= 500 ? 'error' : 'warning',
    suggestions: fallback.suggestions,
    technical: {
      code,
      requestId: error.requestId,
      statusCode: error.statusCode,
      retryable: error.retryable,
      details,
    },
  };
}
