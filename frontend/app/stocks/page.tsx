"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface Stock {
  id: number;
  name: string;
}

export default function StocksPage() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = "http://127.0.0.1:8000/api";

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/stocks/`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch stocks");
        return res.json();
      })
      .then((data) => setStocks(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const handleSearch = (query: string) => {
    const q = query.toLowerCase();
    setStocks((prev) =>
      prev.filter((s) => s.name.toLowerCase().includes(q))
    );
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Stocks</h1>

      <input
        type="text"
        placeholder="Search stock..."
        className="border px-3 py-2 mb-4 w-full rounded"
        onChange={(e) => handleSearch(e.target.value)}
      />

      {loading && <p>Loading stocks...</p>}
      {error && <p className="text-red-600">{error}</p>}

      <ul className="space-y-1">
        {stocks.map((stock) => (
          <li key={stock.id}>
            <Link
              href={`/stocks/${stock.id}`}
              className="text-blue-600 hover:underline"
            >
              {stock.name}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
