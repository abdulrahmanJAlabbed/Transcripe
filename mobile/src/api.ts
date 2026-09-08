import { Directory, File, Paths } from "expo-file-system";

/** Where the local engine lives, as seen from this phone. Set in .env. */
export const API =
  process.env.EXPO_PUBLIC_API_URL?.replace(/\/+$/, "") || "http://127.0.0.1:8000";

/** A studio open to the network prints a token on startup. */
const TOKEN = process.env.EXPO_PUBLIC_API_TOKEN?.trim() || "";

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return TOKEN ? { ...extra, "X-Transcripe-Token": TOKEN } : extra;
}

export type Delivered = { download: string; filename: string };
export type Health = {
  auth_required?: boolean;
  authorized?: boolean;
  features?: Record<string, boolean>;
};

async function detail(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return data?.detail || data?.message || `Engine failed (HTTP ${res.status}).`;
  } catch {
    return `Engine failed (HTTP ${res.status}).`;
  }
}

/** null = unreachable. Otherwise the engine's own view of this client. */
export async function health(signal?: AbortSignal): Promise<Health | null> {
  try {
    const res = await fetch(`${API}/api/health`, {
      headers: authHeaders(),
      signal
    });
    if (!res.ok) return null;
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}

/** Ask the engine for a link download, then stream it straight to disk —
 *  never buffer a whole video in JS memory. */
/** Results live in the cache; without this they pile up until the OS decides
 *  to reclaim, which on a phone full of videos can be a lot of storage. */
export function pruneCache(maxAgeMs = 24 * 60 * 60 * 1000): void {
  try {
    const dir = new Directory(Paths.cache, "transcripe");
    if (!dir.exists) return;
    const cutoff = Date.now() - maxAgeMs;
    for (const entry of dir.list()) {
      // modificationTime is already epoch milliseconds.
      if (entry instanceof File && (entry.modificationTime ?? 0) < cutoff) {
        entry.delete();
      }
    }
  } catch {
    /* best effort — never block the app over housekeeping */
  }
}

async function pull(job: Delivered): Promise<File> {
  const dir = new Directory(Paths.cache, "transcripe");
  if (!dir.exists) dir.create({ intermediates: true });
  const dest = new File(dir, job.filename);
  if (dest.exists) dest.delete();
  await File.downloadFileAsync(`${API}${job.download}`, dest, {
    idempotent: true,
    headers: authHeaders()
  });
  return dest;
}

export async function convertUrl(
  input: {
    url: string;
    format: string;
    useBrowserCookies: boolean;
    /** "best" takes the highest resolution; "compatible" sticks to H.264,
     *  which older players need but YouTube caps at 1080p. */
    quality?: "best" | "compatible";
  },
  signal?: AbortSignal
): Promise<File> {
  const res = await fetch(`${API}/api/convert/url`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ ...input, deliver: "link" }),
    signal
  });
  if (!res.ok) throw new Error(await detail(res));
  return pull((await res.json()) as Delivered);
}

/** Whisper runs for minutes, so this is a job: start, poll, then pull. */
export async function cancelJob(job: string): Promise<void> {
  try {
    await fetch(`${API}/api/jobs/${job}/cancel`, {
      method: "POST",
      headers: authHeaders()
    });
  } catch {
    /* the laptop will time the job out on its own */
  }
}

export async function transcribeFile(
  input: { uri: string; name: string; mimeType?: string; format: string },
  onStage: (stage: string) => void,
  onJob: (job: string) => void,
  signal?: AbortSignal
): Promise<File> {
  const body = new FormData();
  body.append("file", {
    uri: input.uri,
    name: input.name,
    type: input.mimeType || "application/octet-stream"
  } as unknown as Blob);
  body.append("targetFormat", input.format);

  const started = await fetch(`${API}/api/transcribe`, {
    method: "POST",
    headers: authHeaders(),
    body,
    signal
  });
  if (!started.ok) throw new Error(await detail(started));
  const { job, model } = (await started.json()) as { job: string; model: string };
  onJob(job);

  for (;;) {
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    await new Promise((r) => setTimeout(r, 1500));
    const res = await fetch(`${API}/api/jobs/${job}`, {
      headers: authHeaders(),
      signal
    });
    if (!res.ok) throw new Error(await detail(res));
    const state = (await res.json()) as {
      status: string;
      stage?: string;
      detail?: string;
      download?: string;
      filename?: string;
    };
    if (state.status === "error") throw new Error(state.detail || "Transcription failed");
    if (state.status === "cancelled") throw new DOMException("aborted", "AbortError");
    onStage(state.stage || `transcribing with ${model}`);
    if (state.status === "done" && state.download && state.filename) {
      return pull({ download: state.download, filename: state.filename });
    }
  }
}

/** Server-side conversion as a job, so the phone can show ffmpeg's own
 *  progress rather than a bar that means nothing. */
export async function convertFile(
  input: {
    uri: string;
    name: string;
    mimeType?: string;
    format: string;
    /** Images only: an upload limit to land under, in bytes. */
    maxSize?: number;
  },
  onProgress?: (fraction: number, stage: string) => void,
  onJob?: (job: string) => void,
  signal?: AbortSignal
): Promise<File> {
  const body = new FormData();
  // React Native's FormData takes this {uri,name,type} shape for file parts.
  body.append("file", {
    uri: input.uri,
    name: input.name,
    type: input.mimeType || "application/octet-stream"
  } as unknown as Blob);
  body.append("targetFormat", input.format);
  body.append("deliver", "job");
  if (input.maxSize) body.append("maxSize", String(input.maxSize));

  const res = await fetch(`${API}/api/convert/file`, {
    method: "POST",
    headers: authHeaders(),
    body,
    signal
  });
  if (!res.ok) throw new Error(await detail(res));
  const { job } = (await res.json()) as { job: string };
  onJob?.(job);

  for (;;) {
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    await new Promise((r) => setTimeout(r, 800));
    const poll = await fetch(`${API}/api/jobs/${job}`, {
      headers: authHeaders(),
      signal
    });
    if (!poll.ok) throw new Error(await detail(poll));
    const state = (await poll.json()) as {
      status: string;
      progress?: number;
      stage?: string;
      detail?: string;
      download?: string;
      filename?: string;
    };
    if (state.status === "error") throw new Error(state.detail || "Conversion failed");
    if (state.status === "cancelled") throw new DOMException("aborted", "AbortError");
    onProgress?.(state.progress ?? 0, state.stage ?? "");
    if (state.status === "done" && state.download && state.filename) {
      return pull({ download: state.download, filename: state.filename });
    }
  }
}
