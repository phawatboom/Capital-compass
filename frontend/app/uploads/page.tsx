"use client";

import { useEffect, useState } from "react";
import axios from "axios";

export default function UploadsPage() {
  const [uploads, setUploads] = useState([]);

  const fetchUploads = async () => {
    try {
      const response = await axios.get("http://127.0.0.1:8000/api/csv-uploads/");
      setUploads(response.data);
    } catch (err) {
      console.error(err);
    }
  };

  const handleDownload = (fileId) => {
    window.location.href = `http://127.0.0.1:8000/api/csv-uploads/${fileId}/download/`;
  };

  useEffect(() => {
    fetchUploads();
  }, []);

  return (
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
  );
}
