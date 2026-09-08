import { useEffect, useRef, useState } from "react";
import { api } from "../token";

type Job = {
  kind: string;
  name: string;
  target: string;
  bytes?: number;
  seconds?: number;
  elapsed?: number;
  ok?: boolean;
  at?: number;
};

type Stats = {
  uptime: number;
  cores: number;
  parallel: number;
  totals: { jobs: number; failed: number; bytes_in: number; bytes_out: number; seconds: number };
  active: Job[];
  recent: Job[];
};

function human(bytes: number) {
  if (!bytes) return "0";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const n = bytes / 1024 ** i;
  return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)}${units[i]}`;
}

function duration(seconds: number) {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

/** Counts toward a new value instead of snapping to it. */
function useCountUp(value: number) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  const raf = useRef(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const begin = from.current;
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / 700);
      const eased = 1 - Math.pow(1 - k, 3);
      setShown(begin + (value - begin) * eased);
      if (k < 1) raf.current = requestAnimationFrame(step);
      else from.current = value;
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [value]);

  return shown;
}

function Metric({
  label,
  value,
  format
}: {
  label: string;
  value: number;
  format: (n: number) => string;
}) {
  const shown = useCountUp(value);
  return (
    <div className="metric">
      <span className="metric-value">{format(shown)}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}

/** Bar-per-job history: how long each recent conversion actually took. */
function Sparkline({ jobs }: { jobs: Job[] }) {
  const points = jobs.slice(0, 18).reverse();
  const max = Math.max(0.4, ...points.map((j) => j.seconds ?? 0));
  return (
    <div className="spark" aria-hidden="true">
      {points.map((job, i) => (
        <span
          key={`${job.at}-${i}`}
          className={`spark-bar ${job.ok === false ? "failed" : ""}`}
          style={{ height: `${Math.max(8, ((job.seconds ?? 0) / max) * 100)}%` }}
          title={`${job.name} → .${job.target} · ${job.seconds}s`}
        />
      ))}
      {points.length === 0 && <span className="spark-empty">no jobs yet</span>}
    </div>
  );
}

export function LiveStats() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const res = await api("/api/stats", { signal: AbortSignal.timeout(6000) });
        if (!res.ok) return;
        const data = (await res.json()) as Stats;
        if (alive) setStats(data);
      } catch {
        /* the heartbeat already reports reachability */
      }
    };
    pull();
    // Fast enough to feel live, slow enough to stay out of the way.
    const t = window.setInterval(pull, 3000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  /* Nothing to report is not a status worth reporting. An engine that isn't
     answering shows up where it matters — in a conversion that needs it. */
  if (!stats) return null;

  const busy = stats.active.length > 0;

  return (
    <div className={`live ${busy ? "is-busy" : ""}`}>
      <div className="live-head">
        <span className={`live-dot ${busy ? "busy" : "on"}`} />
        <span className="live-title">
          {busy ? `working · ${stats.active.length} job${stats.active.length > 1 ? "s" : ""}` : "engine idle"}
        </span>
        <span className="live-host">
          {stats.cores} cores · {stats.parallel} at a time · up {duration(stats.uptime)}
        </span>
      </div>

      <div className="live-metrics">
        <Metric label="conversions" value={stats.totals.jobs} format={(n) => String(Math.round(n))} />
        <Metric label="data in" value={stats.totals.bytes_in} format={human} />
        <Metric label="data out" value={stats.totals.bytes_out} format={human} />
        <Metric
          label="engine time"
          value={stats.totals.seconds}
          format={(n) => (n < 60 ? `${n.toFixed(1)}s` : duration(n))}
        />
        <Metric label="failed" value={stats.totals.failed} format={(n) => String(Math.round(n))} />
      </div>

      <Sparkline jobs={stats.recent} />

      <div className="live-feed">
        {stats.active.map((job, i) => (
          <div className="feed-row running" key={`a-${i}`}>
            <span className="feed-kind">{job.kind}</span>
            <span className="feed-name">{job.name}</span>
            <span className="feed-meta">→ .{job.target}</span>
            <span className="feed-time">{job.elapsed}s</span>
          </div>
        ))}
        {stats.recent.slice(0, busy ? 3 : 4).map((job, i) => (
          <div className={`feed-row ${job.ok ? "" : "failed"}`} key={`r-${job.at}-${i}`}>
            <span className="feed-kind">{job.kind}</span>
            <span className="feed-name">{job.name}</span>
            <span className="feed-meta">
              → .{job.target}
              {job.bytes ? ` · ${human(job.bytes)}` : ""}
            </span>
            <span className="feed-time">{job.ok ? `${job.seconds}s` : "failed"}</span>
          </div>
        ))}
        {stats.recent.length === 0 && !busy && (
          <div className="feed-row empty">nothing converted yet — drop a file above</div>
        )}
      </div>
    </div>
  );
}
