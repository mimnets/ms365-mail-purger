import { useEffect, useState } from "react";
import { getHistory, deleteJobRecord } from "../api/client";
import { useNavigate } from "react-router-dom";

const STATUS_COLORS = {
  QUEUED: "text-yellow-400",
  RUNNING: "text-blue-400",
  COMPLETE: "text-green-400",
  FAILED: "text-red-400",
  STOPPED: "text-gray-400",
};

export default function HistoryPage() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = () => {
    setLoading(true);
    getHistory()
      .then(res => setJobs(res.data.jobs || []))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleDelete = async (jobId, status) => {
    if (status === "RUNNING") {
      alert("Stop the job before deleting.");
      return;
    }
    if (!confirm("Delete this job record?")) return;
    await deleteJobRecord(jobId);
    load();
  };

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Job History</h2>
      {loading ? (
        <p className="text-gray-400">Loading...</p>
      ) : jobs.length === 0 ? (
        <p className="text-gray-500">No jobs yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-400 border-b border-gray-700">
              <th className="pb-2">User</th>
              <th className="pb-2">Date Range</th>
              <th className="pb-2">Deleted</th>
              <th className="pb-2">Status</th>
              <th className="pb-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map(j => (
              <tr key={j.id} className="border-b border-gray-800 hover:bg-gray-800">
                <td className="py-2">{j.user_email}</td>
                <td className="py-2">{j.date_from} → {j.date_to}</td>
                <td className="py-2">{j.total_deleted?.toLocaleString()}</td>
                <td className="py-2">
                  <span className={`text-xs font-bold ${STATUS_COLORS[j.status] || "text-gray-400"}`}>{j.status}</span>
                </td>
                <td className="py-2 flex gap-2">
                  <button onClick={() => navigate(`/dashboard/${j.id}`)}
                    className="text-blue-400 hover:underline text-xs">View</button>
                  <button onClick={() => handleDelete(j.id, j.status)}
                    className="text-red-400 hover:underline text-xs">Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
