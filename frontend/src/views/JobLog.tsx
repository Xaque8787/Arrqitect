import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../api";
import type { Job, JobStep } from "../api";

function stepClass(status: string) {
  if (status === "success") return "success";
  if (status === "continue_success") return "degraded";
  if (status === "failed" || status === "timeout") return "failed";
  if (status === "running") return "running";
  if (status === "skipped") return "skipped";
  return "";
}

function groupStatus(steps: JobStep[]): string {
  if (steps.some(s => s.status === "failed" || s.status === "timeout")) return "failed";
  if (steps.some(s => s.status === "running")) return "running";
  if (steps.some(s => s.status === "continue_success")) return "degraded";
  if (steps.every(s => s.status === "success" || s.status === "skipped" || s.status === "continue_success")) return "success";
  return "pending";
}

function BulkStepGroup({ slug, steps }: { slug: string; steps: JobStep[] }) {
  const status = groupStatus(steps);
  const [open, setOpen] = useState(status === "failed" || status === "running");

  return (
    <div style={{ border: "1px solid var(--color-border)", borderRadius: 8, overflow: "hidden", marginBottom: 6 }}>
      <button
        style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", background: "var(--color-surface-2)", border: "none", cursor: "pointer", textAlign: "left" }}
        onClick={() => setOpen(o => !o)}
      >
        {open ? <ChevronDown size={14} style={{ flexShrink: 0 }} /> : <ChevronRight size={14} style={{ flexShrink: 0 }} />}
        <span style={{ fontWeight: 600, fontSize: 13, flex: 1 }}>{slug}</span>
        <span style={{ fontSize: 11, color: "var(--color-text-dim)" }}>{steps.length} step{steps.length !== 1 ? "s" : ""}</span>
        <span className={`badge badge-${status}`}>{status}</span>
      </button>
      {open && (
        <div style={{ padding: "4px 0" }}>
          {steps.map((step, i) => {
            const localName = step.step.includes(":") ? step.step.split(":").slice(1).join(":") : step.step;
            return (
              <div key={`${step.step}-${i}`} className={`step-item ${stepClass(step.status)}`} style={{ borderRadius: 0, borderLeft: "none", borderRight: "none" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span className="step-name">{localName}</span>
                    <span className={`badge badge-${step.status}`}>{step.status}</span>
                  </div>
                  {step.log && <div className="step-log">{step.log}</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
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
  const terminalRef = useRef(false);

  useEffect(() => {
    if (!id) return;

    const TERMINAL = new Set(["success", "degraded", "failed", "cancelled", "obsolete"]);

    const fetchSnapshot = () =>
      api.jobs.get(id).then(j => {
        setJob(j);
        if (!terminalRef.current) {
          setJobStatus(j.status);
        }
        if (TERMINAL.has(j.status)) {
          terminalRef.current = true;
          setJobStatus(j.status);
          setSteps(j.job_steps ?? []);
        }
        setLoading(false);
      });

    fetchSnapshot();

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/jobs/${id}`);
    wsRef.current = ws;

    ws.onmessage = e => {
      const data = JSON.parse(e.data);
      if (data.type === "step") {
        setSteps(prev => {
          const idx = prev.findIndex(s => s.step === data.step);
          if (idx >= 0 && TERMINAL.has(prev[idx].status)) {
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
        terminalRef.current = TERMINAL.has(data.status);
        setJobStatus(data.status);
      }
    };

    // On disconnect, refetch canonical state unconditionally — the job may have
    // completed between the drop and now, so HTTP is the only reliable source.
    ws.onclose = () => { fetchSnapshot(); };
    ws.onerror = () => { fetchSnapshot(); };

    return () => ws.close();
  }, [id]);

  if (loading) return <div className="loading-center"><div className="spinner" /></div>;
  if (!job) return <div style={{ padding: 32, color: "var(--color-text-muted)" }}>Job not found.</div>;

  const isActive = jobStatus === "pending" || jobStatus === "running";
  const isDegraded = jobStatus === "degraded";
  const isBulk = job.type === "bulk_install";

  const bulkGroups: Record<string, JobStep[]> = {};
  const flatSteps: JobStep[] = [];

  if (isBulk) {
    for (const step of steps) {
      const colonIdx = step.step.indexOf(":");
      const group = colonIdx >= 0 ? step.step.slice(0, colonIdx) : "__global__";
      if (!bulkGroups[group]) bulkGroups[group] = [];
      bulkGroups[group].push(step);
    }
  } else {
    flatSteps.push(...steps);
  }

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
          {job.is_reconcile && <span className="tag">reconcile</span>}
          {isDegraded && <span className="tag tag-warn">degraded execution</span>}
          {isActive && <div className="spinner" style={{ width: 16, height: 16 }} />}
        </div>
      </div>

      <div className="step-list">
        {isBulk ? (
          Object.entries(bulkGroups).map(([slug, groupSteps]) =>
            slug === "__global__"
              ? groupSteps.map((step, i) => (
                <div key={`${step.step}-${i}`} className={`step-item ${stepClass(step.status)}`}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <span className="step-name">{step.step}</span>
                      <span className={`badge badge-${step.status}`}>{step.status}</span>
                    </div>
                    {step.log && <div className="step-log">{step.log}</div>}
                  </div>
                </div>
              ))
              : <BulkStepGroup key={slug} slug={slug} steps={groupSteps} />
          )
        ) : (
          flatSteps.map((step, i) => (
            <div key={`${step.step}-${i}`} className={`step-item ${stepClass(step.status)}`}>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span className="step-name">{step.step}</span>
                  <span className={`badge badge-${step.status}`}>{step.status}</span>
                </div>
                {step.log && <div className="step-log">{step.log}</div>}
              </div>
            </div>
          ))
        )}
        {steps.length === 0 && isActive && (
          <div style={{ color: "var(--color-text-dim)", fontSize: 13 }}>Waiting for steps...</div>
        )}
      </div>
      <div ref={bottomRef} />
    </div>
  );
}
