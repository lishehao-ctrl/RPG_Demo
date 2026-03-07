import { formatApiError, type ErrorPresentationContext } from '@/shared/lib/apiErrorPresentation';

type ErrorBannerProps = {
  error: unknown;
  context?: ErrorPresentationContext;
};

export function ErrorBanner({ error, context = 'generic' }: ErrorBannerProps) {
  if (!error) {
    return null;
  }

  const presentation = formatApiError(error, context);
  const borderTone = presentation.severity === 'error' ? 'border-[rgba(239,126,69,0.28)] bg-[rgba(239,126,69,0.1)] text-[#ffcfb7]' : 'border-[rgba(245,179,111,0.28)] bg-[rgba(245,179,111,0.1)] text-[#f9dfb7]';

  return (
    <div className={`rounded-[24px] ${borderTone} px-4 py-4 text-sm`}>
      <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-[var(--text-dim)]">{presentation.title}</div>
      <div className="mt-2 break-words leading-7">{presentation.message}</div>

      {presentation.suggestions.length > 0 ? (
        <div className="mt-3 space-y-1 text-xs leading-6 text-[var(--text-mist)]">
          {presentation.suggestions.map((suggestion) => (
            <div key={suggestion}>- {suggestion}</div>
          ))}
        </div>
      ) : null}

      <details className="mt-3 rounded-[16px] border border-[var(--line)] bg-[rgba(0,0,0,0.12)] px-3 py-2 text-xs text-[var(--text-mist)]">
        <summary className="cursor-pointer list-none font-semibold uppercase tracking-[0.14em] text-[var(--text-dim)]">
          Show technical details
        </summary>
        <div className="mt-3 space-y-2 break-words">
          <div>Code: {presentation.technical.code ?? 'unknown'}</div>
          <div>Status: {presentation.technical.statusCode ?? 'unknown'}</div>
          <div>Retryable: {presentation.technical.retryable === null ? 'unknown' : String(presentation.technical.retryable)}</div>
          {presentation.technical.requestId ? <div>Request ID: {presentation.technical.requestId}</div> : null}
          {Object.keys(presentation.technical.details).length > 0 ? (
            <pre className="custom-scrollbar overflow-x-auto rounded-[14px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] p-3 text-[11px] leading-6 text-[var(--text-mist)]">
              {JSON.stringify(presentation.technical.details, null, 2)}
            </pre>
          ) : null}
        </div>
      </details>
    </div>
  );
}
