import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { listUsers, searchPreview, startPurge } from "../api/client";

export default function PurgePage() {
  const navigate = useNavigate();
  const [users, setUsers] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [purging, setPurging] = useState(false);

  useEffect(() => {
    listUsers().then(res => setUsers(res.data.users || []));
  }, []);

  const handlePreview = async () => {
    if (!selectedEmail || !dateFrom || !dateTo) return;
    setPreviewLoading(true);
    try {
      const res = await searchPreview({ user_email: selectedEmail, date_from: dateFrom, date_to: dateTo });
      setPreview(res.data);
    } catch (e) {
      alert("Preview failed: " + (e.response?.data?.detail || e.message));
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleStartPurge = async () => {
    if (!selectedEmail || !dateFrom || !dateTo) return;
    if (!confirm(`Delete ALL emails in ${selectedEmail} between ${dateFrom} and ${dateTo}?\n\nThis cannot be undone.`)) return;
    setPurging(true);
    try {
      const res = await startPurge({ user_email: selectedEmail, date_from: dateFrom, date_to: dateTo });
      navigate(`/dashboard/${res.data.id}`);
    } catch (e) {
      alert("Failed to start purge: " + (e.response?.data?.detail || e.message));
      setPurging(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold mb-6">Search & Purge</h2>

      <div className="space-y-4">
        <div>
          <label className="block text-sm text-gray-400 mb-1">Select Mailbox</label>
          <select
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
            value={selectedEmail}
            onChange={e => { setSelectedEmail(e.target.value); setPreview(null); }}
          >
            <option value="">-- Select user --</option>
            {users.map(u => (
              <option key={u.id} value={u.mail || u.userPrincipalName}>
                {u.displayName} ({u.mail || u.userPrincipalName})
              </option>
            ))}
          </select>
        </div>

        <div className="flex gap-4">
          <div className="flex-1">
            <label className="block text-sm text-gray-400 mb-1">Date From</label>
            <input type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setPreview(null); }}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white" />
          </div>
          <div className="flex-1">
            <label className="block text-sm text-gray-400 mb-1">Date To</label>
            <input type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); setPreview(null); }}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white" />
          </div>
        </div>

        <button
          onClick={handlePreview}
          disabled={previewLoading || !selectedEmail || !dateFrom || !dateTo}
          className="w-full bg-gray-700 hover:bg-gray-600 text-white py-2 rounded disabled:opacity-50"
        >
          {previewLoading ? "Counting..." : "Preview Count"}
        </button>

        {preview && (
          <div className="bg-gray-800 rounded p-4 border border-gray-700">
            <p className="text-lg">Found: <span className="text-yellow-400 font-bold">{preview.estimated_count.toLocaleString()}</span> emails</p>
            <p className="text-sm text-gray-400">in {selectedEmail} between {dateFrom} and {dateTo}</p>
          </div>
        )}

        <button
          onClick={handleStartPurge}
          disabled={purging || !selectedEmail || !dateFrom || !dateTo}
          className="w-full bg-red-600 hover:bg-red-700 text-white font-bold py-3 rounded disabled:opacity-50"
        >
          {purging ? "Starting..." : "Start Purge"}
        </button>
      </div>
    </div>
  );
}
