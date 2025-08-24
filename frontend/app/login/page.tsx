"use client";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import api from "../lib/api";
import { useAuth } from "../lib/authContext";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";
  const { login } = useAuth();

  useEffect(() => {
    api.get("/auth/csrf/");
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await login(username, password); // updates shared auth state
      router.replace(next);
    } catch (err: any) {
      setMsg(err?.response?.data?.error ?? "Login failed");
    }
  };

  return (
    <div style={{ padding: "2rem", maxWidth: 400 }}>
      <h1>Login</h1>
      <form onSubmit={onSubmit}>
                <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
          style={{
            display: "block",
            marginBottom: 12,
            padding: "8px",
            width: "100%",
            boxSizing: "border-box",
          }}
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          style={{
            display: "block",
            marginBottom: 12,
            padding: "8px",
            width: "100%",
            boxSizing: "border-box",
          }}
        />
        <button type="submit" style={{ marginTop: 12 }}>Sign in</button>
      </form>
      {msg && <p style={{ color: "red" }}>{msg}</p>}
    </div>
  );
}
