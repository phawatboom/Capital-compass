"use client";

import { useEffect, useState } from "react";
import api from "../lib/api";
import RequireAuth from "../lib/requireAuth";

export default function UploadsPage() {
  const [uploads, setUploads] = useState([]);

  const fetchUploads = async () => {
    try {
      const response = await api.get("/csv-uploads/");
      setUploads(response.data);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDownload = (id:number) => {
    window.location.href = `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api"}/csv-uploads/${id}/download/`;
  };

  useEffect(() => {
    fetchUploads();
  }, []);

  return (
      <RequireAuth>
    <div style={{ padding: "2rem" }}>
      <h1>Uploaded CSVs</h1>
      <ul style={{ marginTop: "1rem" }}>
        {uploads.map((upload) => (
          <li key={upload.id} style={{ marginBottom: "0.5rem" }}>
            {upload.filename || upload.file} - {new Date(upload.uploaded_at).toLocaleString()}
            <button
              onClick={() => handleDownload(upload.id)}
              style={{
                marginLeft: "1rem",
                backgroundColor: "gray",
                color: "white",
                border: "none",
                borderRadius: "5px",
                padding: "0.25rem 0.5rem",
                cursor: "pointer",
              }}
            >
              Download
            </button>
          </li>
        ))}
      </ul>
    </div>
        </RequireAuth>
  );
}
