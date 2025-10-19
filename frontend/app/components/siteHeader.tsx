"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BarChart3, Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/app/lib/authContext";

/** Small circular avatar with image or initial fallback */
function AvatarCircle({
  username,
  avatarUrl,
  size = 32, // px
}: {
  username?: string;
  avatarUrl?: string | null;
  size?: number;
}) {
  const initial = (username?.trim()?.[0] ?? "U").toUpperCase();
  return (
    <div
      className="overflow-hidden rounded-full ring-1 ring-border bg-gray-100 text-gray-600 grid place-items-center"
      style={{ width: size, height: size }}
    >
      {avatarUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={avatarUrl} alt="Your profile" className="h-full w-full object-cover" />
      ) : (
        <span className="text-sm font-semibold">{initial}</span>
      )}
    </div>
  );
}

/** Simple portal for the mobile drawer */
function Portal({ children }: { children: React.ReactNode }) {
  const [host, setHost] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const node = document.createElement("div");
    document.body.appendChild(node);
    setHost(node);
    return () => {
      document.body.removeChild(node);
    };
  }, []);

  if (!host) return null;
  // Lazy import inside client to avoid SSR issues
  const { createPortal } = require("react-dom");
  return createPortal(children, host);
}

export default function SiteHeader() {
  const { me, loading, logout } = useAuth();
  const { authenticated, username } = me as any;

  const [open, setOpen] = useState(false);

  // Optional: fetch avatar URL if your auth context doesn't include it.
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    if (!authenticated) {
      setAvatarUrl(null);
      return;
    }

    // If your auth context already has an avatar URL, prefer it
    const inContext =
      (me as any)?.avatarUrl ||
      (me as any)?.avatar_url ||
      null;

    if (inContext) {
      setAvatarUrl(inContext);
      return;
    }

    // Otherwise, fetch once from /api/me
    const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/auth/me/`, { credentials: "include" });
        if (!r.ok) return;
        const data = await r.json();
        if (!ignore) setAvatarUrl(data?.avatar_url ?? null);
      } catch {
        // ignore errors; fallback to initial
      }
    })();

    return () => {
      ignore = true;
    };
  }, [authenticated, me]);

  // Lock scroll while the drawer is open; restore on unmount.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const NavLinks = ({ onClick }: { onClick?: () => void }) => (
    <>
      <Link href="/" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>
        Home
      </Link>
      <Link href="/uploads" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>
        My Data
      </Link>
      {/*<Link href="/dashboard" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>*/}
      {/*  Dashboard*/}
      {/*</Link>*/}
      {/*<Link href="/reports" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>*/}
      {/*  Reports*/}
      {/*</Link>*/}
      <Link href="/upload" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>
        Upload Data
      </Link>
      <Link href="/stocks" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>
        Stocks
      </Link>
      <Link href="/beta" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>
        Beta Analysis
      </Link>
    </>
  );

  const AuthArea = () => {
    if (loading) return <span className="opacity-60">…</span>;
    if (authenticated) {
      return (
        <div className="flex items-center gap-4">
          {/* Profile link with avatar (desktop) */}
          <Link
            href="/profile"
            className="group inline-flex items-center gap-2"
            aria-label="Your profile"
            title="Your profile"
          >
            <AvatarCircle username={username} avatarUrl={avatarUrl} />
            <span className="hidden sm:inline text-gray-700 dark:text-gray-200 group-hover:underline">
              Profile
            </span>
          </Link>

          <Button size="sm" onClick={logout}>Log out</Button>
        </div>
      );
    }
    return (
      <div className="flex items-center gap-3">
        <Link href="/login">
          <Button size="sm">Log in</Button>
        </Link>
        <Link href="/register" className="hidden sm:block">
          <Button variant="secondary" size="sm">Register</Button>
        </Link>
      </div>
    );
  };

  return (
    <header className="sticky top-0 z-50 border-b bg-white/80 backdrop-blur print:hidden dark:bg-background/80">
      <div className="mx-auto flex h-16 max-w-screen-2xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand */}
        <Link href="/" className="flex items-center gap-2">
          <BarChart3 className="h-7 w-7 text-blue-600" aria-hidden />
          <span className="text-xl font-bold text-gray-900 dark:text-foreground">Capital Compass</span>
          <span className="sr-only">Go to home</span>
        </Link>

        {/* Desktop navigation */}
        <nav className="hidden md:flex items-center gap-6">
          <NavLinks />
        </nav>

        {/* Desktop auth */}
        <div className="hidden md:flex items-center gap-4">
          <AuthArea />
        </div>

        {/* Mobile hamburger */}
        <div className="md:hidden">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Open menu"
            onClick={() => setOpen(true)}
          >
            <Menu className="h-6 w-6" />
          </Button>
        </div>
      </div>

      {/* Mobile drawer via portal (outside header stacking context) */}
      {open && (
        <Portal>
          {/* Scrim */}
          <div
            className="fixed inset-0 z-[60] bg-black/40"
            aria-hidden
            onClick={() => setOpen(false)}
          />

          {/* Panel */}
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Mobile navigation"
            className="fixed right-0 top-0 z-[70] h-screen w-80 max-w-[85%] translate-x-0 bg-white shadow-xl outline-none transition-transform duration-200 will-change-transform dark:bg-gray-900"
          >
            <div className="flex items-center justify-between border-b px-4 py-4">
              <div className="flex items-center gap-2">
                <BarChart3 className="h-6 w-6 text-blue-600" />
                <span className="text-lg font-semibold">Capital Compass</span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Close menu"
                onClick={() => setOpen(false)}
              >
                <X className="h-6 w-6" />
              </Button>
            </div>

            {/* Mobile profile link (visible when authenticated) */}
            {(authenticated && !loading) && (
              <div className="px-4 pt-3">
                <Link
                  href="/profile"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-3 rounded-md px-2 py-2 hover:bg-gray-50 dark:hover:bg-gray-800"
                  aria-label="Your profile"
                  title="Your profile"
                >
                  <AvatarCircle username={username} avatarUrl={avatarUrl} size={40} />
                  <div className="flex flex-col">
                    <span className="font-medium">{username}</span>
                    <span className="text-sm text-gray-500 dark:text-gray-400">View profile</span>
                  </div>
                </Link>
              </div>
            )}

            <div className="flex flex-col gap-3 px-4 py-6 text-base">
              <NavLinks onClick={() => setOpen(false)} />
            </div>

            <div className="border-t px-4 py-4">
              {loading ? (
                <span className="opacity-60">…</span>
              ) : authenticated ? (
                <div className="flex flex-col gap-3">
                  <span className="text-gray-700 dark:text-gray-200">
                    Signed in as <strong>{username}</strong>
                  </span>
                  <Button onClick={logout}>Log out</Button>
                </div>
              ) : (
                <div className="grid gap-3">
                  <Link href="/login" onClick={() => setOpen(false)}>
                    <Button className="w-full">Log in</Button>
                  </Link>
                  <Link href="/register" onClick={() => setOpen(false)}>
                    <Button className="w-full" variant="secondary">Register</Button>
                  </Link>
                </div>
              )}
            </div>
          </div>
        </Portal>
      )}
    </header>
  );
}
