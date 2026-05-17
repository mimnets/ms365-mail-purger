import axios from "axios";

const api = axios.create({
  baseURL: "http://localhost:8000",
  withCredentials: true,
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export const authLogin = () => api.post("/api/auth/login");
export const getMe = () => api.get("/api/auth/me");

export const listUsers = () => api.get("/api/users");
export const getMailboxStats = (email) => api.get(`/api/users/${encodeURIComponent(email)}/stats`);

export const searchPreview = (data) => api.post("/api/search/preview", data);
export const startPurge = (data) => api.post("/api/purge/start", data);
export const getJobStatus = (jobId) => api.get(`/api/purge/status/${jobId}`);
export const stopJob = (jobId) => api.post(`/api/purge/stop/${jobId}`);

export const getHistory = () => api.get("/api/jobs/history");
export const deleteJob = (jobId) => api.delete(`/api/jobs/${jobId}`);

export default api;
