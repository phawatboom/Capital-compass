"use client";

import { useEffect, useMemo, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/app/lib/authContext";
import api from "@/app/lib/api";
import { Eye, EyeOff } from "lucide-react";

function safeNext(n: string | null | undefined): string {
  if (!n) return "/";
  try {
    const u = new URL(n, window.location.origin);
    if (u.origin !== window.location.origin) return "/";
    return u.pathname + u.search + u.hash;
  } catch {
    return n.startsWith("/") ? n : "/";
  }
}

function LoginPageInner() {
  const router = useRouter();
  const search = useSearchParams();
  const nextParam = search.get("next") || "/";
  const { login, me, loading: authLoading } = useAuth();

  // Form state
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // UI state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);
  const [capsOn, setCapsOn] = useState(false);

  useEffect(() => {
    api.get("/auth/csrf/");
  }, []);

  useEffect(() => {
    if (!authLoading && me.authenticated) {
      router.replace(safeNext(nextParam));
    }
  }, [authLoading, me.authenticated, nextParam, router]);

  const disabled = useMemo(
    () => submitting || username.trim() === "" || password === "",
    [submitting, username, password]
  );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      router.replace(safeNext(nextParam));
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? "Invalid username or password";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  if (me.authenticated) return null;

  return (
    <div className="mx-auto grid min-h-[60vh] max-w-md place-items-center">
      <div className="w-full">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Access your Capital Compass account
          </p>
        </div>

        <div className="rounded-2xl border bg-card shadow-sm">
          <div className="p-6 sm:p-8">
            {error ? (
              <div
                role="alert"
                className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
                aria-live="assertive"
              >
                {error}
              </div>
            ) : null}

            <form onSubmit={onSubmit} className="grid gap-4">
              <div className="grid gap-2">
                <label htmlFor="username" className="text-sm font-medium">
                  Username
                </label>
                <input
                  id="username"
                  name="username"
                  inputMode="text"
                  autoComplete="username"
                  placeholder="e.g. hchemla"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="block w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm outline-none transition focus:ring-2 focus:ring-ring"
                  required
                />
              </div>

              <div className="grid gap-2">
                <div className="flex items-center justify-between">
                  <label htmlFor="password" className="text-sm font-medium">
                    Password
                  </label>
                </div>

                <div className="relative">
                  <input
                    id="password"
                    type={showPw ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyUp={(e) =>
                      setCapsOn(
                        (e as any).getModifierState &&
                          (e as any).getModifierState("CapsLock")
                      )
                    }
                    placeholder="••••••••"
                    autoComplete="current-password"
                    required
                    className="block w-full rounded-md border bg-background px-3 py-2 pr-10 text-sm shadow-sm outline-none transition focus:ring-2 focus:ring-ring"
                  />
                  <button
                    type="button"
                    aria-label={showPw ? "Hide password" : "Show password"}
                    className="absolute inset-y-0 right-0 grid w-10 place-items-center text-muted-foreground hover:text-foreground"
                    onClick={() => setShowPw((v) => !v)}
                  >
                    {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>

                {capsOn && (
                  <div className="mt-1 text-xs text-amber-600">
                    Caps Lock is on
                  </div>
                )}
              </div>

              <button
                type="submit"
                disabled={disabled}
                className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm transition focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
          </div>
        </div>

        <div className="mt-6 text-center text-sm">
          <span className="text-muted-foreground">No account?</span>{" "}
          <a
            href={`/register?next=${encodeURIComponent(nextParam)}`}
            className="font-medium underline-offset-2 hover:underline"
          >
            Create one
          </a>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={
      <div className="grid min-h-[40vh] place-items-center text-sm text-muted-foreground">
        Loading…
      </div>
    }>
      <LoginPageInner />
    </Suspense>
  );
}
