import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api } from "../api";
import type { Job, JobStep } from "../api";

function stepClass(status: string) {
  if (status === "success") return "success";
  if (status === "failed") return "failed";
  if (status === "running") return "running";
  return "";
}

export default function JobLog() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [steps, setSteps] = useState<JobStep[]>([]);
  const [jobStatus, setJobStatus] = useState<string>("pending");
  const [loading, setLoading] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!id) return;

    const TERMINAL = new Set(["success", "failed", "cancelled"]);

    api.jobs.get(id).then(j => {
      setJob(j);
      setJobStatus(j.status);
      // HTTP is the source of truth only for terminal jobs — WS owns step state for active jobs
      if (TERMINAL.has(j.status)) {
        setSteps(j.job_steps ?? []);
      }
      setLoading(false);
    });

    // WS always opens — reducer decides whether to apply or ignore
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/jobs/${id}`);
    wsRef.current = ws;

    ws.onmessage = e => {
      const data = JSON.parse(e.data);
      if (data.type === "step") {
        setSteps(prev => {
          const idx = prev.findIndex(s => s.step === data.step);
          if (idx >= 0 && TERMINAL.has(prev[idx].status)) {
            // Never overwrite a terminal step — discard the incoming message
            return prev;
          }
          const updated: JobStep = {
            id: "",
            job_id: id,
            step: data.step,
            status: data.status,
            log: data.log,
            started_at: null,
            finished_at: null,
          };
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = updated;
            return next;
          }
          return [...prev, updated];
        });
        setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
      } else if (data.type === "job_status") {
        setJobStatus(data.status);
      }
    };

    return () => ws.close();
  }, [id]);

  if (loading) return <div className="loading-center"><div className="spinner" /></div>;
  if (!job) return <div style={{ padding: 32, color: "var(--color-text-muted)" }}>Job not found.</div>;

  const isActive = jobStatus === "pending" || jobStatus === "running";

  return (
    <div>
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate(-1)}>
            <ArrowLeft size={14} />
          </button>
          <div>
            <div className="page-title">Job: {job.type}</div>
            <div className="page-subtitle">{job.id}</div>
          </div>
          <span className={`badge badge-${jobStatus}`}>{jobStatus}</span>
          {job.dry_run && <span className="tag">dry run</span>}
          {isActive && <div className="spinner" style={{ width: 16, height: 16 }} />}
        </div>
      </div>

      <div className="step-list">
        {steps.map((step, i) => (
          <div key={`${step.step}-${i}`} className={`step-item ${stepClass(step.status)}`}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span className="step-name">{step.step}</span>
                <span className={`badge badge-${step.status}`}>{step.status}</span>
              </div>
              {step.log && <div className="step-log">{step.log}</div>}
            </div>
          </div>
        ))}
        {steps.length === 0 && isActive && (
          <div style={{ color: "var(--color-text-dim)", fontSize: 13 }}>Waiting for steps...</div>
        )}
      </div>
      <div ref={bottomRef} />
    </div>
  );
}
