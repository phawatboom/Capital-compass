"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BarChart3, Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/app/lib/authContext";


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
  const { authenticated, username } = me;
  const [open, setOpen] = useState(false);

  // Lock scroll while the drawer is open; restore on unmount.
  useEffect(() => {
    if (open) {
      const prev = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = prev;
      };
    }
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
      <Link href="/dashboard" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>
        Dashboard
      </Link>
      <Link href="/reports" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>
        Reports
      </Link>
      <Link href="/upload" className="py-2 text-gray-700 hover:text-gray-900" onClick={onClick}>
        Upload Data
      </Link>
    </>
  );

  const AuthArea = () => {
    if (loading) return <span className="opacity-60">…</span>;
    if (authenticated) {
      return (
        <div className="flex items-center gap-3">
          <span className="hidden sm:inline text-gray-700 dark:text-gray-200">Hi, {username}</span>
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
          {/*<Link href="/upload">*/}
          {/*  /!*<Button>Get Started</Button>*!/*/}
          {/*</Link>*/}
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
