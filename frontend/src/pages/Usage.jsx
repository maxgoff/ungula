import { useState, useEffect } from 'react';
import { usage } from '../api';

const RANGES = [
  { label: 'Today', days: 1 },
  { label: '7 Days', days: 7 },
  { label: '30 Days', days: 30 },
];

function formatNumber(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString();
}

function StatCard({ label, value, sub }) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">{label}</div>
      <div className="text-2xl font-bold text-white">{formatNumber(value)}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  );
}

function BarChart({ data, maxHeight = 120 }) {
  if (!data.length) return null;
  const maxVal = Math.max(...data.map((d) => d.total_tokens), 1);

  return (
    <div className="flex items-end gap-1" style={{ height: maxHeight }}>
      {data.map((d, i) => {
        const h = Math.max((d.total_tokens / maxVal) * maxHeight, 2);
        return (
          <div key={i} className="flex-1 flex flex-col items-center justify-end group relative">
            <div
              className="w-full bg-indigo-500 rounded-t hover:bg-indigo-400 transition-colors cursor-default"
              style={{ height: h }}
            />
            <div className="absolute bottom-full mb-1 hidden group-hover:block bg-gray-700 text-white text-xs px-2 py-1 rounded whitespace-nowrap z-10">
              {d.date}: {formatNumber(d.total_tokens)} tokens
            </div>
            {(i === 0 || i === data.length - 1 || i === Math.floor(data.length / 2)) && (
              <div className="text-[10px] text-gray-500 mt-1 truncate w-full text-center">
                {d.date.slice(5)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function Usage() {
  const [selectedRange, setSelectedRange] = useState(30);
  const [summary, setSummary] = useState(null);
  const [daily, setDaily] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const now = new Date();
      const start = new Date(now);
      start.setDate(start.getDate() - selectedRange);

      const [summaryData, dailyData] = await Promise.all([
        usage.summary({ startDate: start.toISOString(), endDate: now.toISOString() }),
        usage.daily(selectedRange),
      ]);
      setSummary(summaryData);
      setDaily(dailyData.days || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [selectedRange]);

  const totals = summary?.totals || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, request_count: 0 };
  const breakdown = summary?.breakdown || [];

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Token Usage</h1>
        <div className="flex gap-1 bg-gray-800 rounded-lg p-1 border border-gray-700">
          {RANGES.map((r) => (
            <button
              key={r.days}
              onClick={() => setSelectedRange(r.days)}
              className={`px-3 py-1 text-sm rounded-md transition-colors ${
                selectedRange === r.days
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-900/40 border border-red-700 rounded-lg text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-gray-400 text-sm">Loading usage data...</div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-4 gap-3 mb-6">
            <StatCard label="Total Tokens" value={totals.total_tokens} />
            <StatCard label="Prompt Tokens" value={totals.prompt_tokens} />
            <StatCard label="Completion Tokens" value={totals.completion_tokens} />
            <StatCard label="Requests" value={totals.request_count} />
          </div>

          {/* Daily chart */}
          <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 mb-6">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Daily Usage</h2>
            {daily.length > 0 ? (
              <BarChart data={daily} />
            ) : (
              <div className="text-gray-500 text-sm text-center py-8">No usage data for this period</div>
            )}
          </div>

          {/* Breakdown table */}
          {breakdown.length > 0 && (
            <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-hidden">
              <h2 className="text-sm font-semibold text-gray-300 px-4 py-3 border-b border-gray-700">
                Breakdown by Provider / Model
              </h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-400 text-xs uppercase">
                    <th className="text-left px-4 py-2">Provider</th>
                    <th className="text-left px-4 py-2">Model</th>
                    <th className="text-right px-4 py-2">Prompt</th>
                    <th className="text-right px-4 py-2">Completion</th>
                    <th className="text-right px-4 py-2">Total</th>
                    <th className="text-right px-4 py-2">Requests</th>
                  </tr>
                </thead>
                <tbody>
                  {breakdown.map((row, i) => (
                    <tr key={i} className="border-t border-gray-700/50 text-gray-300 hover:bg-gray-700/30">
                      <td className="px-4 py-2">{row.provider}</td>
                      <td className="px-4 py-2 font-mono text-xs">{row.model}</td>
                      <td className="px-4 py-2 text-right">{formatNumber(row.prompt_tokens)}</td>
                      <td className="px-4 py-2 text-right">{formatNumber(row.completion_tokens)}</td>
                      <td className="px-4 py-2 text-right font-medium text-white">{formatNumber(row.total_tokens)}</td>
                      <td className="px-4 py-2 text-right">{row.request_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
