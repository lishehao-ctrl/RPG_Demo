import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '@/shared/api/service';
import { ApiClientError } from '@/shared/api/client';
import { useAuthStore } from '@/shared/store/authStore';
import { Button } from '@/shared/ui/Button';
import { ErrorBanner } from '@/shared/ui/ErrorBanner';
import { Field } from '@/shared/ui/Field';

export function LoginPage() {
  const navigate = useNavigate();
  const setToken = useAuthStore((state) => state.setToken);
  const [email, setEmail] = useState('admin@example.com');
  const [password, setPassword] = useState('admin123456');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiClientError | Error | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const response = await apiService.login({ email, password });
      setToken(response.access_token);
      navigate('/author/stories');
    } catch (caught) {
      setError(caught as ApiClientError | Error);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-shell flex min-h-screen items-center justify-center px-4 py-6 md:px-8">
      <div className="grid w-full max-w-6xl overflow-hidden rounded-[36px] border border-[var(--line)] bg-[rgba(10,9,12,0.72)] shadow-[0_50px_140px_rgba(0,0,0,0.55)] backdrop-blur-2xl lg:grid-cols-[1.1fr_0.9fr]">
        <section className="relative overflow-hidden border-b border-[var(--line)] px-6 py-10 md:px-10 lg:border-b-0 lg:border-r lg:px-12 lg:py-14">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(239,126,69,0.18),transparent_28%),radial-gradient(circle_at_85%_24%,rgba(139,154,98,0.16),transparent_24%),linear-gradient(180deg,rgba(255,248,229,0.04),transparent_45%)]" />
          <div className="relative fade-rise">
            <p className="text-xs uppercase tracking-[0.34em] text-[var(--text-dim)]">Ember Command / Dual Product</p>
            <h1 className="ornament-line mt-6 max-w-xl font-[var(--font-title)] text-4xl leading-tight tracking-[0.08em] text-[var(--text-ivory)] md:text-5xl">
              Author stories. Publish worlds. Then play them for real.
            </h1>
            <p className="mt-8 max-w-xl text-base leading-8 text-[var(--text-mist)]">
              The forge and the runtime now live as separate tracks. Author mode handles generation and publishing.
              Play mode consumes published stories and drives live LLM-backed sessions.
            </p>
          </div>
        </section>

        <section className="flex items-center px-6 py-10 md:px-10 lg:px-12">
          <div className="w-full fade-rise">
            <p className="text-xs uppercase tracking-[0.26em] text-[var(--text-dim)]">Secure Access</p>
            <h2 className="mt-4 font-[var(--font-title)] text-3xl tracking-[0.08em] text-[var(--text-ivory)]">
              Enter the command chamber
            </h2>
            <p className="mt-3 text-sm leading-7 text-[var(--text-mist)]">
              Sign in as admin to enter the author suite and launch published stories into the runtime chamber.
            </p>

            <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
              <Field
                label="Admin Email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
              <Field
                label="Access Phrase"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />

              <ErrorBanner error={error} context="login" />

              <Button type="submit" wide disabled={submitting}>
                {submitting ? 'Opening Gate...' : 'Enter Author Suite'}
              </Button>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}
