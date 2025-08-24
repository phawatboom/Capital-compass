"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "./authContext";

export default function RequireAuth({ children }: { children: React.ReactNode }) {
  const { loading, me } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !me.authenticated) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, me.authenticated, pathname, router]);

  if (loading) return null;               // or a spinner
  if (!me.authenticated) return null;     // we will redirect

  return <>{children}</>;
}
