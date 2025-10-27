"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface Stock {
  id: number;
  name: string;
  b_coefficient?: number;
  p_value?: number;
}

export default function StocksPage() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [filterMode, setFilterMode] = useState<"all" | "trending" | "meanreverting">("all");

  const stocksPerPage = 21;
  const API_BASE = "http://127.0.0.1:8000/api";

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/stocks/${filterMode !== "all" ? `?filter=${filterMode}` : ""}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch stocks");
        return res.json();
      })
      .then((data) => setStocks(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [filterMode]);

  const filteredStocks = stocks.filter((s) =>
    s.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const totalPages = Math.ceil(filteredStocks.length / stocksPerPage);
  const startIndex = (currentPage - 1) * stocksPerPage;
  const currentStocks = filteredStocks.slice(
    startIndex,
    startIndex + stocksPerPage
  );

  const handleSearch = (query: string) => {
    setSearchQuery(query);
    setCurrentPage(1);
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-3xl font-bold mb-6 text-center text-gray-900">Stocks</h1>

      <input
        type="text"
        placeholder="Search stock..."
        className="border px-4 py-2 mb-6 w-full rounded shadow-sm focus:ring focus:ring-blue-300"
        value={searchQuery}
        onChange={(e) => handleSearch(e.target.value)}
      />

      {loading && <p>Loading stocks...</p>}
      {error && <p className="text-red-600">{error}</p>}

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
        {currentStocks.map((stock) => (
          <Link
            key={stock.id}
            href={`/stocks/${stock.id}`}
            className="block p-4 border rounded-lg shadow hover:shadow-md transition hover:bg-blue-50"
          >
            <h2 className="font-semibold text-lg text-gray-800">{stock.name}</h2>
            <p className="text-sm text-gray-500">View details →</p>
          </Link>
        ))}
      </div>

      {totalPages > 1 && (
        <div className="mt-6 flex justify-center items-center gap-2">
          <button
            className="px-3 py-1 border rounded disabled:opacity-50"
            onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
            disabled={currentPage === 1}
          >
            Previous
          </button>
          <span className="px-2">
            Page {currentPage} of {totalPages}
          </span>
          <button
            className="px-3 py-1 border rounded disabled:opacity-50"
            onClick={() => setCurrentPage((p) => Math.min(p + 1, totalPages))}
            disabled={currentPage === totalPages}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}