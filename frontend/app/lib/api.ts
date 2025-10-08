import axios, { AxiosHeaders } from "axios";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api";

function getCookie(name: string) {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(^|; )${name}=([^;]+)`));
  return m ? decodeURIComponent(m[2]) : null;
}

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const method = (config.method ?? "get").toLowerCase();
  const unsafe = !["get", "head", "options", "trace"].includes(method);
  if (unsafe) {
    const token = getCookie("csrftoken");
    if (token) {
      // Normalize whatever headers are there to an AxiosHeaders instance,
      // then set the CSRF header in a type-safe way.
      const headers = AxiosHeaders.from(config.headers);
      headers.set("X-CSRFToken", token);
      config.headers = headers;
    }
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (
      err.response?.status === 401 &&
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/login")
    ) {
      const next = encodeURIComponent(window.location.pathname);
      window.location.href = `/login?next=${next}`;
      return; // stop
    }
    return Promise.reject(err);
  }
);

export const analyzeFile = async (uploadId: number) => {
  return await fetch(`/api/csv-uploads/${uploadId}/analyze/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  }).then(res => res.json());
};

export default api;