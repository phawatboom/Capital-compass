"use client";

import { useEffect, useMemo, useState } from "react";
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

function scorePassword(pw: string) {
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[A-Z]/.test(pw)) s++;
  if (/[a-z]/.test(pw)) s++;
  if (/[0-9]/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  return Math.min(s, 5);
}

export default function RegisterPage() {
  const router = useRouter();
  const search = useSearchParams();
  const nextParam = search.get("next") || "/";
  const { login, me, loading: authLoading } = useAuth();

  // Form state
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  // UI state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [capsPw, setCapsPw] = useState(false);
  const [capsConfirm, setCapsConfirm] = useState(false);

  useEffect(() => {
    api.get("/auth/csrf/");
  }, []);

  useEffect(() => {
    if (!authLoading && me.authenticated) {
      router.replace(safeNext(nextParam));
    }
  }, [authLoading, me.authenticated, nextParam, router]);

  const passwordsMatch = password === confirm && password.length > 0;
  const disabled = useMemo(
    () =>
      submitting ||
      username.trim() === "" ||
      password === "" ||
      confirm === "" ||
      !passwordsMatch,
    [submitting, username, password, confirm, passwordsMatch]
  );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!passwordsMatch) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/auth/register/", { username: username.trim(), password });
      await login(username.trim(), password);
      router.replace(safeNext(nextParam));
    } catch (err: any) {
      const msg =
        err?.response?.data?.error ||
        (Array.isArray(err?.response?.data?.errors) &&
          err?.response?.data?.errors.join(", ")) ||
        "Registration failed";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  const strength = scorePassword(password);
  const labels = ["Very weak", "Weak", "Okay", "Good", "Strong", "Great"];

  if (me.authenticated) return null;

  return (
    <div className="mx-auto grid min-h-[60vh] max-w-md place-items-center">
      <div className="w-full">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Create account</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            One login for uploads, dashboards, and reports
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
                  placeholder="e.g. teahumairangi"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="block w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm outline-none transition focus:ring-2 focus:ring-ring"
                  required
                />
                <p className="text-xs text-muted-foreground">
                  Use 3–30 characters. Letters, numbers, dash, underscore.
                </p>
              </div>

              <div className="grid gap-2">
                <label htmlFor="password" className="text-sm font-medium">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPw ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyUp={(e) =>
                      setCapsPw(
                        (e as any).getModifierState &&
                          (e as any).getModifierState("CapsLock")
                      )
                    }
                    placeholder="At least 8 characters"
                    autoComplete="new-password"
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
                {capsPw && (
                  <div className="mt-1 text-xs text-amber-600">Caps Lock is on</div>
                )}

                {/* Strength hint */}
                <div aria-live="polite" className="mt-2 text-xs text-muted-foreground">
                  <div className="mb-1 h-1.5 overflow-hidden rounded bg-muted">
                    <div
                      className="h-1.5 bg-primary transition-all"
                      style={{ width: `${(strength / 5) * 100}%` }}
                    />
                  </div>
                  <span>{labels[strength]}</span>
                </div>
              </div>

              <div className="grid gap-2">
                <label htmlFor="confirm" className="text-sm font-medium">
                  Confirm password
                </label>
                <div className="relative">
                  <input
                    id="confirm"
                    type={showConfirm ? "text" : "password"}
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    onKeyUp={(e) =>
                      setCapsConfirm(
                        (e as any).getModifierState &&
                          (e as any).getModifierState("CapsLock")
                      )
                    }
                    placeholder="Re-enter your password"
                    autoComplete="new-password"
                    required
                    className="block w-full rounded-md border bg-background px-3 py-2 pr-10 text-sm shadow-sm outline-none transition focus:ring-2 focus:ring-ring"
                    aria-invalid={confirm.length > 0 && !passwordsMatch}
                    aria-describedby="confirm-help"
                  />
                  <button
                    type="button"
                    aria-label={showConfirm ? "Hide password" : "Show password"}
                    className="absolute inset-y-0 right-0 grid w-10 place-items-center text-muted-foreground hover:text-foreground"
                    onClick={() => setShowConfirm((v) => !v)}
                  >
                    {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {capsConfirm && (
                  <div className="mt-1 text-xs text-amber-600">Caps Lock is on</div>
                )}
                <div
                  id="confirm-help"
                  className={`text-xs ${confirm && !passwordsMatch ? "text-destructive" : "text-muted-foreground"}`}
                  aria-live="polite"
                >
                  {confirm && !passwordsMatch ? "Passwords do not match." : "Re-enter the same password."}
                </div>
              </div>

              <button
                type="submit"
                disabled={disabled}
                className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm transition focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? "Creating…" : "Create account"}
              </button>
            </form>
          </div>
        </div>

        <div className="mt-6 text-center text-sm">
          <span className="text-muted-foreground">Already have an account?</span>{" "}
          <a
            href={`/login?next=${encodeURIComponent(nextParam)}`}
            className="font-medium underline-offset-2 hover:underline"
          >
            Sign in
          </a>
        </div>
      </div>
    </div>
  );
}
