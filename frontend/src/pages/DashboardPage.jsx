import { useParams, useNavigate } from "react-router-dom";
import { useJobPolling } from "../hooks/useJobPolling";
import { stopJob } from "../api/client";

const STATUS_COLORS = {
  QUEUED: "bg-yellow-500",
  RUNNING: "bg-blue-500",
  PAUSED: "bg-orange-500",
  COMPLETE: "bg-green-500",
  FAILED: "bg-red-500",
  STOPPED: "bg-gray-500",
};

function formatEta(seconds) {
  if (!seconds) return "--";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h}h ${m}m ${s}s`;
}

export default function DashboardPage() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const { job, error } = useJobPolling(jobId, 3000);

  const handleStop = async () => {
    if (!confirm("Stop this purge job?")) return;
    await stopJob(jobId);
  };

  if (error) return <p className="text-red-400">Error: {error}</p>;
  if (!job) return <p className="text-gray-400">Loading job...</p>;

  const progress = job.total_found > 0
    ? Math.round((job.total_deleted / job.total_found) * 100)
    : 0;

  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Live Dashboard</h2>
        <span className={`text-xs font-bold px-3 py-1 rounded-full text-white ${STATUS_COLORS[job.status] || "bg-gray-500"}`}>
          {job.status}
        </span>
      </div>

      <div className="bg-gray-800 rounded-lg p-6 space-y-4">
        <div>
          <p className="text-gray-400 text-sm">Mailbox</p>
          <p className="font-medium">{job.user_email}</p>
        </div>
        <div>
          <p className="text-gray-400 text-sm">Date Range</p>
          <p className="font-medium">{job.date_from} → {job.date_to}</p>
        </div>

        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-gray-400">Progress</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-3">
            <div
              className="bg-blue-500 h-3 rounded-full transition-all duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4 text-center">
          <div className="bg-gray-900 rounded p-3">
            <p className="text-2xl font-bold text-white">{job.total_found.toLocaleString()}</p>
            <p className="text-xs text-gray-400">Total Found</p>
          </div>
          <div className="bg-gray-900 rounded p-3">
            <p className="text-2xl font-bold text-green-400">{job.total_deleted.toLocaleString()}</p>
            <p className="text-xs text-gray-400">Deleted</p>
          </div>
          <div className="bg-gray-900 rounded p-3">
            <p className="text-2xl font-bold text-yellow-400">{job.total_remaining.toLocaleString()}</p>
            <p className="text-xs text-gray-400">Remaining</p>
          </div>
        </div>

        <div className="text-center">
          <p className="text-gray-400 text-sm">ETA</p>
          <p className="text-xl font-mono">{formatEta(job.eta_seconds)}</p>
        </div>

        {job.error_message && (
          <div className="bg-red-900/50 border border-red-700 rounded p-3">
            <p className="text-red-300 text-sm">{job.error_message}</p>
          </div>
        )}

        {job.status === "RUNNING" && (
          <button
            onClick={handleStop}
            className="w-full bg-red-700 hover:bg-red-600 text-white py-2 rounded font-semibold"
          >
            Stop Job
          </button>
        )}
        {["COMPLETE", "FAILED", "STOPPED"].includes(job.status) && (
          <button
            onClick={() => navigate("/history")}
            className="w-full bg-gray-700 hover:bg-gray-600 text-white py-2 rounded"
          >
            View History
          </button>
        )}
      </div>
    </div>
  );
}
