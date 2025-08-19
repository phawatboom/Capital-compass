"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";

export default function Home() {
  const [file, setFile] = useState(null);
  const [message, setMessage] = useState("");
  const router = useRouter();

  const handleUpload = async () => {
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await axios.post(
        "http://127.0.0.1:8000/api/upload-csv/",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      setMessage({ text: response.data.message, type: "success" });
    } catch (err) {
      setMessage({
        text: err.response?.data?.error || "Upload failed",
        type: "error",
      });
    }
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
        <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files[0])} />
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
            backgroundColor:
              message.type === "success" ? "green" : message.type === "error" ? "red" : "gray",
          }}
        >
          {message.text}
        </div>
      )}

      <div style={{ marginTop: "2rem" }}>
        <button
          onClick={() => router.push("/uploads")}
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

