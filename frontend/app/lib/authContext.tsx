"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import api from "./api";

type Me = {
  authenticated: boolean;
  username: string | null;
  is_staff: boolean;
  is_superuser: boolean;
  is_moderator: boolean;
};

const EMPTY: Me = { authenticated: false, username: null, is_staff: false, is_superuser: false, is_moderator: false };

type AuthContextType = {
  me: Me;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (u: string, p: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me>(EMPTY);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const refresh = useCallback(async () => {
    try {
      await api.get("/auth/csrf/");
      const { data } = await api.get<Me>("/auth/me/");
      setMe(data);
    } catch {
      setMe(EMPTY);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    await api.get("/auth/csrf/");
    await api.post("/auth/login/", { username, password });
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    await api.get("/auth/csrf/");
    await api.post("/auth/logout/");
    setMe(EMPTY);

    // Send user to login, optionally preserving where they were
    const nextParam = pathname && pathname !== "/login" ? `?next=${encodeURIComponent(pathname)}` : "";
    router.replace(`/login${nextParam}`);
    router.refresh(); // invalidate any cached data
  }, [pathname, router]);

  const value = useMemo(() => ({ me, loading, refresh, login, logout }), [me, loading, refresh, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
