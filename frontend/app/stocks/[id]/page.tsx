"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

interface StockRow {
  date: string;
  price: number | null;
  return: number | null;
  equity: number | null;
}

interface Stock {
  id: number;
  name: string;
  data: StockRow[];
}

export default function StockDetailPage() {
  const params = useParams();
  const { id } = params; // stock id from route

  const [stock, setStock] = useState<Stock | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedYear, setSelectedYear] = useState<number | "All">("All");
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 100;

  const API_BASE = "http://127.0.0.1:8000/api";

  // Load stock data
  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/stocks/${id}/`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch stock data");
        return res.json();
      })
      .then((data) => setStock(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  // Extract unique years
  const getYears = () => {
    if (!stock) return [];
    const years = Array.from(
      new Set(stock.data.map((row) => new Date(row.date).getFullYear()))
    );
    return years.sort((a, b) => b - a);
  };

  // Filter & paginate data
  const filteredData = stock
    ? stock.data.filter((row) =>
        selectedYear === "All"
          ? true
          : new Date(row.date).getFullYear() === selectedYear
      )
    : [];

  const paginatedData = filteredData.slice(
    (currentPage - 1) * rowsPerPage,
    currentPage * rowsPerPage
  );

  const totalPages = Math.ceil(filteredData.length / rowsPerPage);

  if (loading) return <p>Loading stock data...</p>;
  if (error) return <p className="text-red-600">{error}</p>;
  if (!stock) return <p>No stock data found</p>;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">{stock.name}</h1>

      {/* Year filter */}
      <div className="mb-4 flex items-center gap-4">
        <label className="font-semibold">Year:</label>
        <select
          className="border px-3 py-2 rounded"
          value={selectedYear}
          onChange={(e) => {
            setSelectedYear(e.target.value === "All" ? "All" : Number(e.target.value));
            setCurrentPage(1);
          }}
        >
          <option value="All">All</option>
          {getYears().map((year) => (
            <option key={year} value={year}>
              {year}
            </option>
          ))}
        </select>
      </div>

      {/* Stock data table */}
      <table className="table-auto border-collapse border border-gray-300 w-full">
        <thead>
          <tr>
            <th className="border px-4 py-2">Date</th>
            <th className="border px-4 py-2">Price</th>
            <th className="border px-4 py-2">Return</th>
            <th className="border px-4 py-2">Equity</th>
          </tr>
        </thead>
        <tbody>
          {paginatedData.map((row, idx) => (
            <tr key={idx}>
              <td className="border px-4 py-2">{row.date}</td>
              <td className="border px-4 py-2">
                {row.price !== null ? row.price : "-"}
              </td>
              <td className="border px-4 py-2">
                {row.return !== null ? `${(row.return * 100).toFixed(2)}%` : "-"}
              </td>
              <td className="border px-4 py-2">
                {row.equity !== null ? row.equity.toFixed(3) : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-4 flex justify-center gap-2">
          <button
            className="px-3 py-1 border rounded disabled:opacity-50"
            onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
            disabled={currentPage === 1}
          >
            Previous
          </button>
          <span>
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
