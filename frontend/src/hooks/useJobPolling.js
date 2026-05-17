import { useState, useEffect, useRef } from "react";
import { getJobStatus } from "../api/client";

export function useJobPolling(jobId, intervalMs = 3000) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    if (!jobId) return;

    const poll = async () => {
      try {
        const res = await getJobStatus(jobId);
        setJob(res.data);
        if (["COMPLETE", "FAILED", "STOPPED"].includes(res.data.status)) {
          clearInterval(intervalRef.current);
        }
      } catch (err) {
        setError(err.message);
      }
    };

    poll();
    intervalRef.current = setInterval(poll, intervalMs);

    return () => clearInterval(intervalRef.current);
  }, [jobId, intervalMs]);

  return { job, error };
}
