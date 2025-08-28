"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import api from "./lib/api";
import { ensureAuthed } from "./lib/ensureAuth";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);
  const router = useRouter();

  useEffect(() => {
    // make sure csrftoken exists
    api.get("/auth/csrf/");
  }, []);

  const handleUpload = async () => {
    if (!file) return;

    // Require login before attempting upload
    if (!(await ensureAuthed("/"))) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      // Updated endpoint to '/upload-file/'
      const res = await api.post("/upload-file/", formData);
      setMessage({ text: res.data.message, type: "success" });
    } catch (err: any) {
      setMessage({
        text: err?.response?.data?.error || "Upload failed",
        type: "error",
      });
    }
  };

  const goToUploads = async () => {
    if (!(await ensureAuthed("/uploads"))) return;
    router.push("/uploads");
  };

  return (
    <div style={{ padding: "2rem" }}>
      <div
        style={{
          backgroundColor: "rgba(128,128,128,0.2)",
          padding: "1rem",
          display: "inline-block",
          borderRadius: "8px",
        }}
      >
        {/* Updated accept attribute to allow both CSV and XLSX files */}
        <input type="file" accept=".csv, .xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>

      <button
        onClick={handleUpload}
        style={{
          backgroundColor: "blue",
          color: "white",
          padding: "0.5rem 1rem",
          marginLeft: "1rem",
          border: "none",
          borderRadius: "5px",
          cursor: "pointer",
        }}
      >
        Upload
      </button>

      {message && (
        <div
          style={{
            marginTop: "1rem",
            padding: "0.5rem",
            borderRadius: "5px",
            color: "white",
            backgroundColor: message.type === "success" ? "green" : "red",
          }}
        >
          {message.text}
        </div>
      )}

      <div style={{ marginTop: "2rem" }}>
        <button
          onClick={goToUploads}
          style={{
            backgroundColor: "gray",
            color: "white",
            padding: "0.5rem 1rem",
            border: "none",
            borderRadius: "5px",
            cursor: "pointer",
          }}
        >
          View Uploaded CSVs
        </button>
      </div>
    </div>
  );
}