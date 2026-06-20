import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getOrgs, listUsers, searchPreview, startPurge } from "../api/client";

export default function PurgePage() {
  const navigate = useNavigate();
  const [orgs, setOrgs] = useState([]);
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [users, setUsers] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [purging, setPurging] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [userSearch, setUserSearch] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);

  const filteredUsers = users.filter(u => {
    const q = userSearch.toLowerCase();
    return (
      u.displayName?.toLowerCase().includes(q) ||
      u.mail?.toLowerCase().includes(q) ||
      u.userPrincipalName?.toLowerCase().includes(q)
    );
  });

  useEffect(() => {
    getOrgs().then(res => {
      setOrgs(res.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const loadUsers = async () => {
    if (!selectedOrgId) return;
    setUsers([]);
    setSelectedEmail("");
    setUserSearch("");
    try {
      const res = await listUsers();
      setUsers(res.data.users || []);
    } catch (e) {
      setError("Failed to load users: " + (e.response?.data?.detail || e.message));
    }
  };

  useEffect(() => {
    if (selectedOrgId) loadUsers();
  }, [selectedOrgId]);

  const handlePreview = async () => {
    if (!selectedEmail || !dateFrom || !dateTo) return;
    setPreviewLoading(true);
    setError(null);
    try {
      const res = await searchPreview({
        org_id: selectedOrgId,
        user_email: selectedEmail,
        date_from: dateFrom,
        date_to: dateTo,
      });
      setPreview(res.data);
    } catch (e) {
      setError("Preview failed: " + (e.response?.data?.detail || e.message));
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleStartPurge = async () => {
    if (!selectedOrgId || !selectedEmail || !dateFrom || !dateTo) return;
    const org = orgs.find(o => o.id === selectedOrgId);
    if (org && !org.has_certificate) {
      setError("This organization has no certificate. Go to Settings and generate one first.");
      return;
    }
    if (!confirm(`Delete ALL emails in ${selectedEmail}'s mailbox (including archive)\nfrom ${dateFrom} to ${dateTo}?\n\nThis is a soft delete — moves to Recoverable Items.\nThis cannot be easily undone.`)) return;
    setPurging(true);
    setError(null);
    try {
      const res = await startPurge({
        org_id: selectedOrgId,
        user_email: selectedEmail,
        date_from: dateFrom,
        date_to: dateTo,
      });
      navigate(`/dashboard/${res.data.id}`);
    } catch (e) {
      setError("Failed to start purge: " + (e.response?.data?.detail || e.message));
      setPurging(false);
    }
  };

  if (loading) return <p className="text-gray-400">Loading...</p>;

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold mb-6">Search & Purge</h2>

      <div className="space-y-4">
        {/* Org Selection */}
        {orgs.length === 0 ? (
          <div className="bg-yellow-900/30 border border-yellow-700 rounded p-4 text-yellow-300 text-sm">
            No organizations configured. Go to <button onClick={() => navigate("/settings")} className="text-blue-400 hover:underline">Settings</button> to add one first.
          </div>
        ) : (
          <div>
            <label className="block text-sm text-gray-400 mb-1">Organization</label>
            <select
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
              value={selectedOrgId}
              onChange={e => { setSelectedOrgId(e.target.value); setPreview(null); setError(null); setUserSearch(""); }}
            >
              <option value="">-- Select organization --</option>
              {orgs.map(o => (
                <option key={o.id} value={o.id}>
                  {o.name} {o.has_certificate ? "✓" : "⚠ No cert"}
                </option>
              ))}
            </select>
          </div>
        )}

        {selectedOrgId && (
          <>
            <div className="relative">
              <label className="block text-sm text-gray-400 mb-1">Search & Select Mailbox</label>
              <input
                type="text"
                placeholder="Type to search users..."
                value={selectedEmail && !userSearch ? users.find(u => (u.mail || u.userPrincipalName) === selectedEmail)?.displayName + ` (${selectedEmail})` || selectedEmail : userSearch}
                onChange={e => {
                  const val = e.target.value;
                  setUserSearch(val);
                  if (!val) { setSelectedEmail(''); setShowDropdown(false); return; }
                  setShowDropdown(true);
                }}
                onFocus={() => { if (userSearch) setShowDropdown(true); }}
                onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white"
              />
              {showDropdown && (
                <div className="absolute z-10 w-full mt-1 bg-gray-800 border border-gray-700 rounded max-h-60 overflow-y-auto shadow-lg">
                  {filteredUsers.length === 0 ? (
                    <div className="px-3 py-2 text-gray-500 text-sm">No users match</div>
                  ) : (
                    filteredUsers.map(u => (
                      <div
                        key={u.id}
                        className={`px-3 py-2 cursor-pointer text-sm hover:bg-gray-700 ${selectedEmail === (u.mail || u.userPrincipalName) ? 'bg-gray-700 text-white' : 'text-gray-300'}`}
                        onMouseDown={() => {
                          setSelectedEmail(u.mail || u.userPrincipalName);
                          setUserSearch(u.displayName + ' (' + (u.mail || u.userPrincipalName) + ')');
                          setShowDropdown(false);
                          setPreview(null);
                          setError(null);
                        }}
                      >
                        <span className="font-medium">{u.displayName}</span>
                        <span className="text-gray-500 ml-2 text-xs">{u.mail || u.userPrincipalName}</span>
                      </div>
                    ))
                  )}
                </div>
              )}
              {selectedEmail && !showDropdown && (
                <div className="mt-1 text-xs text-green-400">
                  Selected: {selectedEmail}
                </div>
              )}
            </div>

            <div className="flex gap-4">
              <div className="flex-1">
                <label className="block text-sm text-gray-400 mb-1">Date From</label>
                <input type="date" value={dateFrom}
                  onChange={e => { setDateFrom(e.target.value); setPreview(null); setError(null); }}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white" />
              </div>
              <div className="flex-1">
                <label className="block text-sm text-gray-400 mb-1">Date To</label>
                <input type="date" value={dateTo}
                  onChange={e => { setDateTo(e.target.value); setPreview(null); setError(null); }}
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

            {error && (
              <div className="bg-red-900/50 border border-red-700 rounded p-3 text-red-300 text-sm">
                {error}
              </div>
            )}

            {preview && (
              <div className="bg-gray-800 rounded p-4 border border-gray-700">
                <p className="text-lg">
                  Found: <span className="text-yellow-400 font-bold">{preview.estimated_count.toLocaleString()}</span> emails
                </p>
                <p className="text-sm text-gray-400">
                  in {selectedEmail}'s mailbox (primary + archive) between {dateFrom} and {dateTo}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  Note: Compliance search count is an estimate. Actual may differ.
                </p>
              </div>
            )}

            <button
              onClick={handleStartPurge}
              disabled={purging || !selectedEmail || !dateFrom || !dateTo}
              className="w-full bg-red-600 hover:bg-red-700 text-white font-bold py-3 rounded disabled:opacity-50"
            >
              {purging ? "Starting..." : "Start Purge"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
