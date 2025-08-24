import api from "./api";

export async function ensureAuthed(nextPath: string): Promise<boolean> {
  try {
    const { data } = await api.get("/auth/me");
    if (data?.authenticated) return true;
  } catch {
    // ignore; treat as unauthenticated
  }
  if (typeof window !== "undefined") {
    window.location.href = `/login?next=${encodeURIComponent(nextPath)}`;
  }
  return false;
}
