"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { DateRange } from "react-date-range";
import { addDays } from "date-fns";

import "react-date-range/dist/styles.css"; // main style
import "react-date-range/dist/theme/default.css"; // theme

interface StockRow {
  date: string;
  price: number | null;
  return: number | null;
  equity: number | null;
}

interface Stock {
  id: number;
  name: string;
  b_coefficient: number | null;
  p_value: number | null;
  data: StockRow[];

}

export default function StockDetailPage() {
  const params = useParams();
  const { id } = params;

  const [stock, setStock] = useState<Stock | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedYear, setSelectedYear] = useState<number | "All">("All");
  const [selectedMonth, setSelectedMonth] = useState<number | "All">("All");
  const [hideEmptyDates, setHideEmptyDates] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [showDateRange, setShowDateRange] = useState(false);
  const [filterMode, setFilterMode] = useState<"simple" | "advanced">("simple");

  const [dateRange, setDateRange] = useState([
    {
      startDate: new Date(),
      endDate: new Date(),
      key: "selection",
    },
  ]);

  const rowsPerPage = 100;
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

  // Load stock data and set initial date range
  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/stocks/${id}/`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch stock data");
        return res.json();
      })
      .then((data) => {
        setStock(data);
        if (data.data.length > 0) {
          const allDates = data.data.map((row: StockRow) => new Date(row.date));
          const minDate = new Date(Math.min(...allDates));
          const maxDate = new Date(Math.max(...allDates));
          setDateRange([
            {
              startDate: minDate,
              endDate: maxDate,
              key: "selection",
            },
          ]);
        }
      })
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

  // Month names
  const months = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];

  // Filter & paginate data
  const filteredData = stock
    ? stock.data.filter((row) => {
        const date = new Date(row.date);

        let isDateValid = false;
        if (filterMode === "advanced") {
          isDateValid = date >= dateRange[0].startDate! && date <= dateRange[0].endDate!;
        } else { // "simple" mode
          const inYear =
            selectedYear === "All" ? true : date.getFullYear() === selectedYear;
          const inMonth =
            selectedMonth === "All" ? true : date.getMonth() === selectedMonth;
          isDateValid = inYear && inMonth;
        }

        const notEmpty =
          !hideEmptyDates ||
          row.price !== null ||
          row.return !== null ||
          row.equity !== null;

        return isDateValid && notEmpty;
      })
    : [];

  const paginatedData = filteredData.slice(
    (currentPage - 1) * rowsPerPage,
    currentPage * rowsPerPage
  );

  const totalPages = Math.ceil(filteredData.length / rowsPerPage);

  // Fancy loading screen
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-t-4 border-blue-600 mb-4"></div>
        <p className="text-lg font-semibold text-gray-800">
          Stock data loading...
        </p>
      </div>
    );
  }

  if (error) return <p className="text-red-600">{error}</p>;
  if (!stock) return <p>No stock data found</p>;

  // Calculate min and max dates for the DateRange component
  const allDates = stock.data.map((row) => new Date(row.date));
  const minDate = new Date(Math.min(...allDates.map(d => d.getTime())));
  const maxDate = new Date(Math.max(...allDates.map(d => d.getTime())));

  return (
    <div className="p-6 max-w-5xl mx-auto">
    <h1 className="text-2xl font-bold mb-4">{stock.name}</h1>

      {/* Filters */}
      <div className="mb-4 flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-4 justify-between">
          {/* Simple Filters */}
          <div className="flex flex-wrap items-center gap-4">
            {/* Year filter */}
            <div>
              <label className="font-semibold mr-2">Year:</label>
              <select
                className="border px-3 py-2 rounded"
                value={selectedYear}
                onChange={(e) => {
                  setSelectedYear(e.target.value === "All" ? "All" : Number(e.target.value));
                  setCurrentPage(1);
                  setFilterMode("simple"); // Ensure simple mode is active
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

            {/* Month filter */}
            <div>
              <label className="font-semibold mr-2">Month:</label>
              <select
                className="border px-3 py-2 rounded"
                value={selectedMonth}
                onChange={(e) => {
                  setSelectedMonth(e.target.value === "All" ? "All" : Number(e.target.value));
                  setCurrentPage(1);
                  setFilterMode("simple"); // Ensure simple mode is active
                }}
              >
                <option value="All">All</option>
                {months.map((m, idx) => (
                  <option key={idx} value={idx}>
                    {m}
                  </option>
                ))}
              </select>
            </div>

            {/* Hide empty dates filter */}
            <div>
              <label className="font-semibold mr-2">Show:</label>
              <select
                className="border px-3 py-2 rounded"
                value={hideEmptyDates ? "nonEmpty" : "all"}
                onChange={(e) => {
                  setHideEmptyDates(e.target.value === "nonEmpty");
                  setCurrentPage(1);
                  setFilterMode("simple"); // Ensure simple mode is active
                }}
              >
                <option value="all">All Dates</option>
                <option value="nonEmpty">Only Dates With Data</option>
              </select>
            </div>
          </div>

          {/* Advanced toggle button */}
          <button
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 w-fit"
            onClick={() => setShowDateRange(true)}
          >
            Advanced Settings
          </button>
        </div>
      </div>

      {/* Date range picker overlay */}
      {showDateRange && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50"
          onClick={() => setShowDateRange(false)}
        >
          <div
            className="relative bg-white p-4 rounded-lg shadow-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-xl font-bold mb-4">Select Date Range</h2>
            <DateRange
              editableDateInputs={true}
              onChange={(item) => {
                setDateRange([item.selection]);
                setCurrentPage(1); // Reset to first page
              }}
              moveRangeOnFirstSelection={false}
              ranges={dateRange}
              minDate={minDate}
              maxDate={maxDate}
            />
            <button
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded w-full hover:bg-blue-700"
              onClick={() => {
                setFilterMode("advanced"); // Switch to advanced mode on click
                setShowDateRange(false);
              }}
            >
              Apply
            </button>
          </div>
        </div>
      )}

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