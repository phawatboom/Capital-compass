"use client";

import { useCallback, useEffect, useState } from "react";
import api from "./api";

type Me = {
  authenticated: boolean;
  username: string | null;
  is_staff: boolean;
  is_superuser: boolean;
  is_moderator: boolean;
};

const EMPTY: Me = {
  authenticated: false,
  username: null,
  is_staff: false,
  is_superuser: false,
  is_moderator: false,
};

export function useAuth() {
  const [me, setMe] = useState<Me>(EMPTY);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<Me>("/auth/me");
      setMe(data);
    } catch {
      setMe(EMPTY);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    api.get("/auth/csrf/").finally(() => {});
    refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await api.get("/auth/csrf/");
      await api.post("/auth/logout/");
    } finally {
      setMe(EMPTY);
      // redirect the user to the login page
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    }
  }, []);

  return { ...me, loading, refresh, logout };
}
