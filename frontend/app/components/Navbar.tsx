"use client";

import Link from "next/link";
import { useAuth } from "../lib/authContext";

export default function Navbar() {
  const { loading, me, logout } = useAuth();
  const { authenticated, username } = me;

  const barStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0.75rem 1rem",
    borderBottom: "1px solid rgba(0,0,0,0.1)",
    position: "sticky",
    top: 0,
    background: "var(--background)",
    zIndex: 10,
  };

  const groupStyle: React.CSSProperties = {
    display: "flex",
    gap: "0.5rem",
    alignItems: "center",
  };

  const linkBtn: React.CSSProperties = {
    backgroundColor: "gray",
    color: "white",
    padding: "0.4rem 0.75rem",
    borderRadius: "6px",
    border: "none",
    cursor: "pointer",
    textDecoration: "none",
  };

  const primaryBtn: React.CSSProperties = {
    backgroundColor: "blue",
    color: "white",
    padding: "0.4rem 0.75rem",
    borderRadius: "6px",
    border: "none",
    cursor: "pointer",
  };

  return (
    <nav style={barStyle}>
      <div>
        <Link href="/" style={{ fontWeight: 700, textDecoration: "none", color: "inherit" }}>
          Capital Compass
        </Link>
      </div>

      <div style={groupStyle}>
        <Link href="/uploads" style={linkBtn}>Uploads</Link>

        {loading ? (
          <span style={{ opacity: 0.6 }}>…</span>
        ) : authenticated ? (
          <>
            <span style={{ opacity: 0.8 }}>Hi, {username}</span>
            <button onClick={logout} style={primaryBtn}>Log out</button>
          </>
        ) : (
          <>
            <Link href="/login" style={primaryBtn}>Log in</Link>
            <Link href="/register" style={linkBtn}>Register</Link>
          </>
        )}
      </div>
    </nav>
  );
}
