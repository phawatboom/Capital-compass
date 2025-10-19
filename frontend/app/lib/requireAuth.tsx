"use client";

import { useEffect, Suspense } from "react";
import { usePathname, useSearchParams, useRouter } from "next/navigation";
import { useAuth } from "./authContext";

function RequireAuthInner({ children }: { children: React.ReactNode }) {
  const { loading, me } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();

  useEffect(() => {
    if (!loading && !me.authenticated) {
      const q = search?.toString();
      const next = encodeURIComponent(`${pathname}${q ? `?${q}` : ""}`);
      router.replace(`/login?next=${next}`);
    }
  }, [loading, me.authenticated, pathname, search, router]);

  if (loading) {
    return (
      <div className="grid min-h-[40vh] place-items-center text-sm text-muted-foreground">
        Checking session…
      </div>
    );
  }
  if (!me.authenticated) return null;

  return <>{children}</>;
}

export default function RequireAuth({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={
      <div className="grid min-h-[40vh] place-items-center text-sm text-muted-foreground">
        Loading…
      </div>
    }>
      <RequireAuthInner>{children}</RequireAuthInner>
    </Suspense>
  );
}
