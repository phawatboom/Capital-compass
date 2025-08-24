"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import api from "../lib/api";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    api.get("/auth/csrf/");
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/auth/register/", { username, password });
      await api.post("/auth/login/", { username, password }); // auto-login
      router.push("/");
    } catch (err: any) {
      setMsg(err?.response?.data?.error || err?.response?.data?.errors?.join(", ") || "Registration failed");
    }
  };

  return (
    <div style={{ padding: "2rem", maxWidth: 400 }}>
      <h1>Create account</h1>
      <form onSubmit={onSubmit}>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
          style={{ display: "block", marginTop: 12, width: "100%" }}
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          style={{ display: "block", marginTop: 12, width: "100%" }}
        />
        <button type="submit" style={{ marginTop: 12 }}>Sign up</button>
      </form>
      {msg && <p style={{ color: "red" }}>{msg}</p>}
    </div>
  );
}
