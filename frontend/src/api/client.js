import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      window.location.href = "/";
    }
    return Promise.reject(err);
  }
);

// ── Auth ──────────────────────────────────────────────────────────────────────
export const getMe = () => api.get("/api/auth/me");

// ── Organizations ─────────────────────────────────────────────────────────────
export const getOrgs = () => api.get("/api/orgs");
export const getOrg = (id) => api.get(`/api/orgs/${id}`);
export const createOrg = (data) => api.post("/api/orgs", data);
export const updateOrg = (id, data) => api.put(`/api/orgs/${id}`, data);
export const deleteOrg = (id) => api.delete(`/api/orgs/${id}`);
export const generateCert = (id) => api.post(`/api/orgs/${id}/certificate`, null, { responseType: "blob" });
export const downloadCert = (id) => api.get(`/api/orgs/${id}/certificate/download`, { responseType: "blob" });

// ── Users ─────────────────────────────────────────────────────────────────────
export const listUsers = () => api.get("/api/users");
export const getMailboxStats = (email) => api.get(`/api/users/${encodeURIComponent(email)}/stats`);

// ── Search / Purge ────────────────────────────────────────────────────────────
export const searchPreview = (data) => api.post("/api/search/preview", data);
export const startPurge = (data) => api.post("/api/purge/start", data);
export const getJobStatus = (jobId) => api.get(`/api/purge/status/${jobId}`);
export const stopJob = (jobId) => api.post(`/api/purge/stop/${jobId}`);

// ── History ───────────────────────────────────────────────────────────────────
export const getHistory = () => api.get("/api/jobs/history");
export const deleteJobRecord = (jobId) => api.delete(`/api/jobs/${jobId}`);

export default api;
