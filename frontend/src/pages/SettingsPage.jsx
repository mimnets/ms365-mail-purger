import { useState, useEffect } from "react";
import { getOrgs, createOrg, deleteOrg, generateCert } from "../api/client";

export default function SettingsPage() {
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    tenant_id: "",
    tenant_domain: "",
    app_client_id: "",
    admin_upn: "",
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [downloading, setDownloading] = useState({});

  const loadOrgs = async () => {
    try {
      const res = await getOrgs();
      setOrgs(res.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadOrgs(); }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const res = await createOrg(form);
      setOrgs(prev => [res.data, ...prev]);
      setShowForm(false);
      setForm({ name: "", tenant_id: "", tenant_domain: "", app_client_id: "", admin_upn: "" });
      setMessage({ type: "success", text: `Organization "${res.data.name}" created. Now generate a certificate!` });
    } catch (e) {
      setMessage({ type: "error", text: e.response?.data?.detail || e.message });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (orgId) => {
    if (!confirm("Delete this organization and all its stored credentials?")) return;
    try {
      await deleteOrg(orgId);
      setOrgs(prev => prev.filter(o => o.id !== orgId));
      setMessage({ type: "success", text: "Organization deleted" });
    } catch (e) {
      setMessage({ type: "error", text: e.response?.data?.detail || e.message });
    }
  };

  const handleGenerateCert = async (orgId) => {
    setDownloading(prev => ({ ...prev, [orgId]: true }));
    setMessage(null);
    try {
      const res = await generateCert(orgId);
      // Download the .cer file
      const blob = new Blob([res.data], { type: "application/x-x509-ca-cert" });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res.headers["content-disposition"]
        ?.match(/filename="?([^"]+)"?/)?.[1] || `cert_${orgId}.cer`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      setMessage({
        type: "success",
        text: "Certificate generated! Upload the downloaded .cer file to Azure AD → App Registration → Certificates & secrets."
      });
      loadOrgs(); // Refresh to show thumbprint
    } catch (e) {
      setMessage({ type: "error", text: e.response?.data?.detail || e.message });
    } finally {
      setDownloading(prev => ({ ...prev, [orgId]: false }));
    }
  };

  if (loading) return <p className="text-gray-400">Loading settings...</p>;

  return (
    <div className="max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Settings</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-semibold"
        >
          {showForm ? "Cancel" : "Add Organization"}
        </button>
      </div>

      {message && (
        <div className={`mb-4 p-3 rounded text-sm ${
          message.type === "success" ? "bg-green-900 border border-green-700 text-green-300"
            : "bg-red-900 border border-red-700 text-red-300"
        }`}>
          {message.text}
        </div>
      )}

      {/* Add Org Form */}
      {showForm && (
        <form onSubmit={handleCreate} className="bg-gray-800 rounded-lg p-6 mb-6 border border-gray-700 space-y-4">
          <h3 className="text-lg font-semibold text-white">New Organization</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Organization Name</label>
              <input type="text" required value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white"
                placeholder="e.g. VCL Bangladesh" />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Tenant ID (Directory ID)</label>
              <input type="text" required value={form.tenant_id}
                onChange={e => setForm(f => ({ ...f, tenant_id: e.target.value }))}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white font-mono text-sm"
                placeholder="b29cd8b5-..." />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Tenant Domain</label>
              <input type="text" required value={form.tenant_domain}
                onChange={e => setForm(f => ({ ...f, tenant_domain: e.target.value }))}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white"
                placeholder="vclbd.onmicrosoft.com" />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">App (Client) ID</label>
              <input type="text" required value={form.app_client_id}
                onChange={e => setForm(f => ({ ...f, app_client_id: e.target.value }))}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white font-mono text-sm"
                placeholder="5f0d4af1-..." />
            </div>
            <div className="col-span-2">
              <label className="block text-sm text-gray-400 mb-1">Admin UPN (for compliance operations)</label>
              <input type="email" required value={form.admin_upn}
                onChange={e => setForm(f => ({ ...f, admin_upn: e.target.value }))}
                className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white"
                placeholder="monir.it@vclbd.net" />
            </div>
          </div>
          <button type="submit" disabled={saving}
            className="bg-green-600 hover:bg-green-700 text-white font-semibold px-6 py-2 rounded disabled:opacity-50">
            {saving ? "Saving..." : "Save Organization"}
          </button>
        </form>
      )}

      {/* Org List */}
      {orgs.length === 0 ? (
        <div className="bg-gray-800 rounded-lg p-8 text-center">
          <p className="text-gray-400">No organizations configured yet.</p>
          <p className="text-gray-500 text-sm mt-2">Click "Add Organization" to get started.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {orgs.map(org => (
            <div key={org.id} className="bg-gray-800 rounded-lg p-5 border border-gray-700">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-lg font-semibold text-white">{org.name}</h3>
                  <p className="text-sm text-gray-400 mt-1">{org.admin_upn}</p>
                </div>
                <button onClick={() => handleDelete(org.id)}
                  className="text-red-400 hover:text-red-300 text-xs">Delete</button>
              </div>

              <div className="grid grid-cols-2 gap-3 mt-4 text-sm">
                <div><span className="text-gray-500">Tenant:</span> <span className="text-gray-300 font-mono">{org.tenant_domain}</span></div>
                <div><span className="text-gray-500">App ID:</span> <span className="text-gray-300 font-mono">{org.app_client_id?.substring(0, 12)}...</span></div>
              </div>

              <div className="mt-4 flex items-center gap-3">
                {org.has_certificate ? (
                  <>
                    <span className="text-xs bg-green-900 text-green-300 px-2 py-1 rounded-full font-semibold">✓ Certificate Ready</span>
                    <button onClick={() => handleGenerateCert(org.id)} disabled={downloading[org.id]}
                      className="text-blue-400 hover:text-blue-300 text-xs underline disabled:opacity-50">
                      {downloading[org.id] ? "Downloading..." : "Re-download .cer"}
                    </button>
                  </>
                ) : (
                  <button onClick={() => handleGenerateCert(org.id)} disabled={downloading[org.id]}
                    className="bg-yellow-600 hover:bg-yellow-700 text-white px-4 py-1.5 rounded text-xs font-semibold disabled:opacity-50">
                    {downloading[org.id] ? "Generating..." : "Generate Certificate"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
