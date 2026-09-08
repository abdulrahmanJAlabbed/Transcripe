import {
  Apple,
  ArrowRight,
  Check,
  Clipboard,
  Copy,
  Download,
  Moon,
  Plus,
  RotateCcw,
  Smartphone,
  Sun,
  X
} from "lucide-react";
import {
  ChangeEvent,
  DragEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { CleanHeroBackground } from "./components/CleanHeroBackground";
import { LiveStats } from "./components/LiveStats";
import Orb from "./components/reactbits/Orb";
import { useScrollReveal, useSpotlight } from "./motion";
import { services, Service } from "./data/services";
import { api, setToken } from "./token";
import {
  canConvertLocally,
  canConvertVideoLocally,
  canFitLocally,
  convertImageLocally,
  convertVideoLocally,
  fitImageLocally,
  parseSize,
  type Dimensions
} from "./local";
// Inlined so the code themes itself (currentColor) and costs no extra request.
import appQr from "./qr-app.svg?raw";
import { applyTheme, currentTheme, watchSystemTheme, type Theme } from "./theme";

/* ── Format knowledge ────────────────────────────────────────────────────── */

const AUDIO_EXTS = ["mp3", "wav", "m4a", "flac", "aac", "ogg", "opus", "wma", "aiff", "alac"];
const VIDEO_EXTS = ["mp4", "mkv", "mov", "webm", "avi", "3gp", "flv", "wmv", "m4v", "mpg", "mpeg", "ts"];
const IMAGE_EXTS = ["png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif", "heic", "heif", "avif", "ico"];
const SUBTITLE_EXTS = ["srt", "vtt", "ass", "ssa"];
const DATA_EXTS = ["csv", "json", "yaml", "yml", "xml", "xlsx", "tsv", "parquet", "toml"];

type Kind = "audio" | "video" | "image" | "subtitle" | "data" | "other";

function kindOf(ext: string): Kind {
  if (AUDIO_EXTS.includes(ext)) return "audio";
  if (VIDEO_EXTS.includes(ext)) return "video";
  if (IMAGE_EXTS.includes(ext)) return "image";
  if (SUBTITLE_EXTS.includes(ext)) return "subtitle";
  if (DATA_EXTS.includes(ext)) return "data";
  return "other";
}

/* Web engine targets per input kind; "other" falls back to the CLI.
   `text` targets go to Whisper rather than ffmpeg. */
const TARGETS: Record<
  Exclude<Kind, "other">,
  { main: string[]; audio?: string[]; text?: string[] }
> = {
  audio: { main: ["mp3", "wav", "m4a", "flac", "ogg", "opus", "aac"], text: ["srt", "txt"] },
  video: {
    main: ["mp4", "webm", "mov", "mkv", "avi"],
    audio: ["mp3", "wav", "m4a", "flac"],
    text: ["srt", "txt"]
  },
  image: { main: ["png", "jpg", "webp", "avif", "bmp", "tiff", "gif", "ico"] },
  subtitle: { main: ["srt", "vtt", "ass", "txt"] },
  data: { main: ["csv", "json", "yaml", "xlsx", "xml"] }
};

const TEXT_TARGETS = ["srt", "txt"];

/* The public demo converts on a server, not on the visitor's machine. Saying
   otherwise would be a lie, so the hosted build says what actually happens.
   Built with VITE_HOSTED=1; the local studio leaves it unset. */
const HOSTED = import.meta.env.VITE_HOSTED === "1";

/* Where the phone buttons and the QR point. Swap this for an `exp://` link
   once the app is published with `eas update` and scanning will launch it
   directly instead of opening the setup notes. */
const APP_QR_TARGET =
  "https://github.com/abdulrahmanJAlabbed/Transcripe/blob/main/mobile/README.md";

const URL_TARGETS = ["mp4", "mp3", "m4a", "wav", "flac"];

/* Every format the engines touch, for the ticker. Duplicated in the DOM so the
   loop is seamless. */
const FORMAT_TICKER = [
  "mp4", "mkv", "mov", "webm", "avi", "mp3", "wav", "flac", "m4a", "ogg",
  "opus", "aac", "srt", "vtt", "ass", "pdf", "docx", "pptx", "xlsx", "epub",
  "png", "jpg", "webp", "avif", "heic", "svg", "tiff", "csv", "json", "yaml",
  "parquet", "xml", "zip", "7z", "tar", "rar", "glb", "obj", "stl", "fbx"
];

const PLATFORMS: Array<[string[], string]> = [
  [["youtube.com", "youtu.be"], "YouTube"],
  [["instagram.com", "instagr.am"], "Instagram"],
  [["tiktok.com"], "TikTok"],
  [["twitter.com", "x.com"], "Twitter / X"],
  [["spotify.com", "spoti.fi"], "Spotify"],
  [["soundcloud.com"], "SoundCloud"],
  [["reddit.com", "redd.it"], "Reddit"],
  [["vimeo.com"], "Vimeo"],
  [["twitch.tv"], "Twitch"],
  [["facebook.com", "fb.watch"], "Facebook"],
  [["threads.net"], "Threads"],
  [["bsky.app"], "Bluesky"],
  [["pinterest.com", "pin.it"], "Pinterest"],
  [["snapchat.com"], "Snapchat"],
  [["dailymotion.com", "dai.ly"], "DailyMotion"],
  [["rumble.com"], "Rumble"],
  [["bilibili.com", "b23.tv"], "Bilibili"],
  [["music.apple.com"], "Apple Music"],
  [["bandcamp.com"], "Bandcamp"],
  [["t.me", "telegram.org"], "Telegram"]
];

function detectPlatform(url: string): string | null {
  const lower = url.trim().toLowerCase();
  if (!lower) return null;
  for (const [hosts, name] of PLATFORMS) {
    if (hosts.some((h) => lower.includes(h))) return name;
  }
  return lower.startsWith("http") ? "direct link" : null;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${(bytes / 1_073_741_824).toFixed(2)} GB`;
}

function extOf(name: string) {
  const parts = name.split("?")[0].split(".");
  return parts.length > 1 ? parts.pop()!.toLowerCase() : "";
}

/* Swap the example filename in a docs command for the user's actual file. */
function personalize(command: string, filename: string) {
  return command.replace(/(?<=\s)[\w.-]+\.[a-z0-9]{1,5}(?=\s|$)/i, filename);
}

function filenameFromDisposition(header: string | null): string {
  if (!header) return "";
  const utf8 = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      /* fall through to the plain filename */
    }
  }
  const plain = header.match(/filename=["']?([^"';]+)["']?/i);
  return plain?.[1]?.trim() ?? "";
}

function triggerDownload(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/* ── Small hooks ─────────────────────────────────────────────────────────── */

function useCopy(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number>(0);
  const copy = (text: string) => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1800);
    });
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return [copied, copy];
}

/* ── Types ───────────────────────────────────────────────────────────────── */

type Entry = { id: string; file: File; ext: string };
type OutFile = { name: string; url: string };
type Phase = "idle" | "working" | "done";
type Mode = "file" | "url";

/* Engines the web studio can run directly — clicking their grid cell arms
   the converter; every other cell copies its CLI one-liner instead. */
const WEB_ABLE: Record<string, Mode> = {
  transcribe: "file",
  "social-downloader": "url",
  "media-convert": "file",
  "image-resize-compress": "file"
};

/* ── App ─────────────────────────────────────────────────────────────────── */

export function App() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const jobsRef = useRef<Set<string>>(new Set());
  const cardRef = useRef<HTMLDivElement>(null);

  const [mode, setMode] = useState<Mode>("file");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [mediaUrl, setMediaUrl] = useState("");
  const [target, setTarget] = useState("");
  const [useCookies, setUseCookies] = useState(true);
  const [linkQuality, setLinkQuality] = useState<"best" | "compatible">("best");
  /* An upload limit to land under, as typed ("500KB"). Empty = no limit. */
  const [maxSize, setMaxSize] = useState("");
  /* Output dimensions in pixels, as typed. Either alone keeps the aspect. */
  const [outWidth, setOutWidth] = useState("");
  const [outHeight, setOutHeight] = useState("");
  /* The picture's own size, read from the file — presets and the "now" label
     both need it, and guessing would put the wrong numbers on screen. */
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  /* The refinements stay folded away until asked for. Most conversions are
     "this file, that format" and want nothing else on screen. */
  const [advanced, setAdvanced] = useState(false);

  const [phase, setPhase] = useState<Phase>("idle");
  const [statusLabel, setStatusLabel] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [outputs, setOutputs] = useState<OutFile[]>([]);

  const [isDragging, setIsDragging] = useState(false);
  const [globalDrag, setGlobalDrag] = useState(false);
  const [engineOnline, setEngineOnline] = useState<boolean | null>(null);
  const [engineLocked, setEngineLocked] = useState(false);
  // What the engine on the other end can actually do. Unknown until the first
  // heartbeat answers, and treated as capable so nothing flickers away.
  const [features, setFeatures] = useState<Record<string, boolean>>({});
  /* The engine's own upload ceiling. It reports one; ignoring it meant a big
     file uploaded until the server cut it off, which reads as a failure with
     no cause. 0 = not heard from it yet. */
  const [maxUploadMb, setMaxUploadMb] = useState(0);
  const [theme, setTheme] = useState<Theme>(() => currentTheme());
  const [localCount, setLocalCount] = useState(0);
  useScrollReveal();
  const spotlightRef = useSpotlight<HTMLDivElement>();
  const [toast, setToast] = useState<{ id: number; msg: string } | null>(null);
  const [copiedEngine, setCopiedEngine] = useState<string | null>(null);
  const [pipCopied, copyPip] = useCopy();
  const [termCopied, copyTerm] = useCopy();
  const [cmdCopied, copyCmd] = useCopy();
  const [offlineCopied, copyOffline] = useCopy();

  const toastTimer = useRef(0);
  const showToast = (msg: string) => {
    setToast({ id: Date.now(), msg });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  };

  const platform = useMemo(() => detectPlatform(mediaUrl), [mediaUrl]);
  // Assume yes until an engine tells us otherwise, so the chips don't flicker.
  const canTranscribe = features.transcribe !== false;
  // An engine without pandas can't do tabular data; don't offer what will fail.
  const engineHandles = (k: Kind | null) =>
    k !== "data" || features.data !== false;
  const kind: Kind | null = entries.length ? kindOf(entries[0].ext) : null;
  /* "auto" is how the engine is asked to choose; it is not a file extension,
     and showing it as one puts ".auto" in front of the user. */
  const targetLabel = target === "auto" ? "the best fit" : `.${target}`;
  /* Only images have a size budget: it is the one job where what the user
     wants is a number of kilobytes, not a different format. */
  const maxBytes = useMemo(
    () => (kind === "image" && maxSize.trim() ? parseSize(maxSize) : null),
    [kind, maxSize]
  );
  const pixels = (raw: string): number | null => {
    const n = Number(raw.trim());
    return raw.trim() && Number.isFinite(n) && n >= 1 && n <= 20000
      ? Math.round(n)
      : null;
  };
  const dims: Dimensions | undefined = useMemo(() => {
    if (kind !== "image") return undefined;
    const w = pixels(outWidth);
    const h = pixels(outHeight);
    return w || h ? { width: w, height: h } : undefined;
  }, [kind, outWidth, outHeight]);
  const badDimension =
    (outWidth.trim() !== "" && pixels(outWidth) === null) ||
    (outHeight.trim() !== "" && pixels(outHeight) === null);
  // Converting a file to the format it already is does nothing useful.
  const sourceExt = entries.length ? entries[0].ext.replace(/^jpeg$/, "jpg") : "";
  /* .srt/.txt mean "transcribe this" only when the input is media; from a
     subtitle file they're an ordinary format change. */
  const isTranscribing =
    TEXT_TARGETS.includes(target) && (kind === "audio" || kind === "video");
  const cliService: Service | null = useMemo(() => {
    if (kind !== "other" || !entries.length) return null;
    const ext = entries[0].ext;
    return services.find((s) => s.inputs.includes(ext)) ?? null;
  }, [kind, entries]);

  /* Elapsed-seconds ticker while the engine works. */
  useEffect(() => {
    if (phase !== "working") return;
    setElapsed(0);
    const t = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [phase]);

  /* Until a side is chosen the stylesheet follows the OS; this keeps the
     browser chrome in step with it. */
  useEffect(watchSystemTheme, []);

  /* Local engine heartbeat. Health is open even on a token-locked studio, so
     "running but locked" reads differently from "not running". */
  useEffect(() => {
    let alive = true;
    // One slow reply on a loaded machine shouldn't announce the engine as
    // dead while it is busy converting; take two misses to call it offline.
    let misses = 0;
    const check = async () => {
      try {
        const res = await api("/api/health", {
          signal: AbortSignal.timeout(8000)
        });
        const info = res.ok ? await res.json().catch(() => null) : null;
        if (!alive) return;
        misses = 0;
        setEngineOnline(res.ok);
        setEngineLocked(!!info?.auth_required && !info?.authorized);
        if (info?.features) setFeatures(info.features);
        if (info?.max_upload_mb) setMaxUploadMb(info.max_upload_mb);
      } catch {
        if (!alive) return;
        misses += 1;
        if (misses >= 2) setEngineOnline(false);
      }
    };
    check();
    const t = window.setInterval(check, 15000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  /* If the engine turns out to have no Whisper, don't leave a transcript
     target armed — it would only fail on submit. */
  useEffect(() => {
    if (canTranscribe || !TEXT_TARGETS.includes(target) || !kind || kind === "other") return;
    setTarget(TARGETS[kind].main[0]);
  }, [canTranscribe, target, kind]);

  /* Arming a size budget changes the question from "which format" to "how
     small", so hand the format choice to the engine until the user takes it
     back — and give it back when the budget goes away. */
  useEffect(() => {
    if (kind !== "image") return;
    if (maxBytes && target !== "auto") setTarget("auto");
    if (!maxBytes && target === "auto") setTarget(TARGETS.image.main[0]);
  }, [maxBytes, kind, target]);

  /* Read the picture's own dimensions so the control can show them and offer
     presets that actually make it smaller. */
  useEffect(() => {
    if (kind !== "image" || !entries.length) {
      setNatural(null);
      return;
    }
    let alive = true;
    createImageBitmap(entries[0].file)
      .then((bmp) => {
        if (alive) setNatural({ width: bmp.width, height: bmp.height });
        bmp.close();
      })
      .catch(() => {
        /* HEIC and friends: the browser can't decode it, so no presets. */
        if (alive) setNatural(null);
      });
    return () => {
      alive = false;
    };
  }, [kind, entries]);

  /* Dimensions and a budget only mean anything for images. */
  useEffect(() => {
    if (kind && kind !== "image") {
      if (maxSize) setMaxSize("");
      if (outWidth) setOutWidth("");
      if (outHeight) setOutHeight("");
    }
  }, [kind, maxSize, outWidth, outHeight]);

  /* Release result blobs when they're replaced. */
  useEffect(
    () => () => outputs.forEach((o) => URL.revokeObjectURL(o.url)),
    [outputs]
  );

  const resetResult = () => {
    setOutputs([]);
    setPhase("idle");
    setError("");
  };

  const addFiles = (list: FileList | File[]) => {
    const next = Array.from(list).map((file, i) => ({
      id: `${Date.now()}-${i}-${file.name}`,
      file,
      ext: extOf(file.name)
    }));
    if (!next.length) return;
    setEntries((prev) => {
      const merged = [...prev, ...next];
      const k = kindOf(merged[0].ext);
      if (k !== "other") {
        const opts = TARGETS[k];
        const from = merged[0].ext.replace(/^jpeg$/, "jpg");
        const choices = [...opts.main, ...(opts.audio ?? [])].filter(
          (fmt) => fmt !== from
        );
        // Default to something that actually changes the file.
        setTarget((t) => (choices.includes(t) ? t : choices[0] ?? opts.main[0]));
      }
      return merged;
    });
    resetResult();
  };

  /* Anything the page can convert itself never reaches the engine, so the
     engine's upload ceiling doesn't apply to it. */
  const goesToEngine = (entry: Entry) =>
    !canConvertLocally(entry.ext, target) &&
    !canConvertVideoLocally(entry.ext, target) &&
    !(maxBytes && canFitLocally(entry.ext, target));

  const tooBig = useMemo(() => {
    if (!maxUploadMb || mode !== "file") return [];
    const ceiling = maxUploadMb * 1024 * 1024;
    return entries.filter((e) => e.file.size > ceiling && goesToEngine(e));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, maxUploadMb, target, maxBytes, mode]);

  /* One target applies to the whole batch, so files of a different kind than
     the first would fail one by one. Say it up front instead. */
  const strays = useMemo(() => {
    if (entries.length < 2) return [];
    const lead = kindOf(entries[0].ext);
    return entries.filter((e) => kindOf(e.ext) !== lead);
  }, [entries]);

  const onFileInput = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) addFiles(e.target.files);
    e.target.value = "";
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const dragProps = {
    onDragOver: (e: DragEvent) => {
      e.preventDefault();
      setIsDragging(true);
    },
    onDragLeave: () => setIsDragging(false),
    onDrop
  };

  const removeEntry = (id: string) => {
    setEntries((prev) => prev.filter((f) => f.id !== id));
    resetResult();
  };

  const pasteFromClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText();
      const match = text?.match(/https?:\/\/\S+/i);
      if (match) setMediaUrl(match[0]);
      else if (text?.trim()) setMediaUrl(text.trim());
    } catch {
      /* clipboard permission denied — user can type the link */
    }
  };

  const switchMode = (m: Mode) => {
    setMode(m);
    setError("");
    if (m === "url") {
      setTarget((t) => (URL_TARGETS.includes(t) ? t : "mp4"));
      if (!mediaUrl) pasteFromClipboard();
    } else if (entries.length && kind && kind !== "other") {
      const opts = TARGETS[kind];
      setTarget((t) =>
        [...opts.main, ...(opts.audio ?? [])].includes(t) ? t : opts.main[0]
      );
    }
  };

  /* Latest handlers behind stable refs so window listeners bind once. */
  const addFilesRef = useRef(addFiles);
  addFilesRef.current = addFiles;

  /* Drop anywhere on the page — not just the little box. */
  useEffect(() => {
    let depth = 0;
    const hasFiles = (e: globalThis.DragEvent) =>
      e.dataTransfer?.types.includes("Files");
    const onEnter = (e: globalThis.DragEvent) => {
      if (!hasFiles(e)) return;
      depth++;
      setGlobalDrag(true);
    };
    const onLeave = (e: globalThis.DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setGlobalDrag(false);
    };
    const onOver = (e: globalThis.DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    const onDrop = (e: globalThis.DragEvent) => {
      depth = 0;
      setGlobalDrag(false);
      if (!e.dataTransfer?.files.length) return;
      e.preventDefault();
      setMode("file");
      addFilesRef.current(e.dataTransfer.files);
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("drop", onDrop);
    };
  }, []);

  /* Paste anywhere: files convert, links arm the URL mode. */
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const target = e.target instanceof HTMLElement ? e.target : null;
      if (target?.closest("input, textarea")) return;
      const files = e.clipboardData?.files;
      if (files?.length) {
        setMode("file");
        addFilesRef.current(files);
        return;
      }
      const text = e.clipboardData?.getData("text") ?? "";
      const match = text.match(/https?:\/\/\S+/i);
      if (match) {
        setMode("url");
        setTarget((t) => (URL_TARGETS.includes(t) ? t : "mp4"));
        setMediaUrl(match[0]);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  /* ── Conversion ──────────────────────────────────────────────────────── */

  const failDetail = async (res: Response) => {
    const data = await res.json().catch(() => null);
    return data?.detail || data?.message || `Engine failed (HTTP ${res.status}).`;
  };

  const runUrlConvert = async (signal: AbortSignal): Promise<OutFile[]> => {
    setStatusLabel(`Fetching ${platform ?? "link"} → .${target}`);
    const res = await api("/api/convert/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: mediaUrl.trim(),
        format: target || "mp4",
        useBrowserCookies: useCookies,
        quality: linkQuality
      }),
      signal
    });
    if (!res.ok) throw new Error(await failDetail(res));
    const blob = await res.blob();
    const name =
      filenameFromDisposition(res.headers.get("content-disposition")) ||
      `transcripe.${target || "mp4"}`;
    return [{ name, url: URL.createObjectURL(blob) }];
  };

  /* Whisper takes minutes, so transcription is a job: start it, poll it,
     then collect the file through the same one-shot link. */
  const runTranscribe = async (
    file: File,
    prefix: string,
    signal: AbortSignal
  ): Promise<OutFile> => {
    const body = new FormData();
    body.append("file", file);
    body.append("targetFormat", target);
    setStatusLabel(`${prefix}${file.name} → ${targetLabel}`);
    const started = await api("/api/transcribe", { method: "POST", body, signal });
    if (!started.ok) throw new Error(`${file.name}: ${await failDetail(started)}`);
    const { job, model } = await started.json();
    jobsRef.current.add(job);

    for (;;) {
      if (signal.aborted) throw new DOMException("aborted", "AbortError");
      await new Promise((r) => setTimeout(r, 1500));
      const res = await api(`/api/jobs/${job}`, { signal });
      if (!res.ok) throw new Error(`${file.name}: ${await failDetail(res)}`);
      const state = await res.json();
      if (state.status === "error") throw new Error(`${file.name}: ${state.detail}`);
      if (state.stage) setStatusLabel(`${prefix}${state.stage}`);
      else setStatusLabel(`${prefix}transcribing ${file.name} with ${model}`);
      if (state.status === "cancelled") {
        throw new DOMException("aborted", "AbortError");
      }
      if (state.status === "done") {
        jobsRef.current.delete(job);
        const dl = await api(state.download, { signal });
        if (!dl.ok) throw new Error(`${file.name}: could not fetch the transcript`);
        return {
          name: state.filename,
          url: URL.createObjectURL(await dl.blob())
        };
      }
    }
  };

  /* Server-side conversions run as a job so ffmpeg's own progress can be
     shown, instead of a bar that slides about telling you nothing. */
  const convertOnServer = async (
    file: File,
    signal: AbortSignal,
    label: (text: string) => void
  ): Promise<OutFile> => {
    const body = new FormData();
    body.append("file", file);
    body.append("targetFormat", target);
    body.append("deliver", "job");
    if (maxBytes) body.append("maxSize", String(maxBytes));
    if (dims?.width) body.append("width", String(dims.width));
    if (dims?.height) body.append("height", String(dims.height));
    const started = await api("/api/convert/file", { method: "POST", body, signal });
    if (!started.ok) throw new Error(`${file.name}: ${await failDetail(started)}`);
    const { job } = await started.json();
    jobsRef.current.add(job);

    for (;;) {
      if (signal.aborted) throw new DOMException("aborted", "AbortError");
      await new Promise((r) => setTimeout(r, 700));
      const res = await api(`/api/jobs/${job}`, { signal });
      if (!res.ok) throw new Error(`${file.name}: ${await failDetail(res)}`);
      const state = await res.json();
      if (state.status === "error") throw new Error(`${file.name}: ${state.detail}`);
      if (state.status === "cancelled") throw new DOMException("aborted", "AbortError");
      const pct = Math.round((state.progress ?? 0) * 100);
      label(`${file.name} → ${targetLabel}${pct ? ` · ${pct}%` : ""}`);
      if (state.status === "done") {
        jobsRef.current.delete(job);
        const dl = await api(state.download, { signal });
        if (!dl.ok) throw new Error(`${file.name}: could not fetch the result`);
        return { name: state.filename, url: URL.createObjectURL(await dl.blob()) };
      }
    }
  };

  const convertOne = async (
    file: File,
    signal: AbortSignal,
    label?: (text: string) => void
  ): Promise<OutFile> => {
    /* The visitor's machine first: no upload, no queue, no engine needed.
       Doubly so for a size budget — the reason to shrink a photo is usually
       that it is about to be uploaded somewhere, and this way the original
       never travels to get there. */
    const from = extOf(file.name);
    if (maxBytes) {
      if (canFitLocally(from, target)) {
        try {
          const done = await fitImageLocally(file, target, maxBytes, dims);
          setLocalCount((n) => n + 1);
          return { name: done.name, url: URL.createObjectURL(done.blob) };
        } catch {
          /* browser couldn't decode it, or couldn't reach the budget */
        }
      }
      if (label) return convertOnServer(file, signal, label);
    } else if (canConvertLocally(from, target)) {
      try {
        const done = await convertImageLocally(file, target, dims);
        setLocalCount((n) => n + 1);
        return { name: done.name, url: URL.createObjectURL(done.blob) };
      } catch {
        /* browser couldn't decode it — hand it to the engine instead */
      }
    }
    if (canConvertVideoLocally(from, target)) {
      try {
        setStatusLabel(`${file.name} → ${targetLabel} · on this device`);
        const done = await convertVideoLocally(file, target, (p) =>
          setStatusLabel(
            `${file.name} → ${targetLabel} · on this device · ${Math.round(p * 100)}%`
          )
        );
        setLocalCount((n) => n + 1);
        return { name: done.name, url: URL.createObjectURL(done.blob) };
      } catch {
        /* container or codec the page can't handle — the engine can */
      }
    }

    if (label) return convertOnServer(file, signal, label);

    const body = new FormData();
    body.append("file", file);
    body.append("targetFormat", target);
    if (maxBytes) body.append("maxSize", String(maxBytes));
    if (dims?.width) body.append("width", String(dims.width));
    if (dims?.height) body.append("height", String(dims.height));
    const res = await api("/api/convert/file", { method: "POST", body, signal });
    if (!res.ok) throw new Error(`${file.name}: ${await failDetail(res)}`);
    const blob = await res.blob();
    const name =
      filenameFromDisposition(res.headers.get("content-disposition")) ||
      `${file.name.replace(/\.[^.]+$/, "")}.${target === "auto" ? "img" : target}`;
    return { name, url: URL.createObjectURL(blob) };
  };

  /* The engine converts several files at once, so a batch shouldn't queue
     itself single-file. Keep a few in flight and report progress by count;
     transcription stays one at a time, since Whisper is serialized anyway. */
  const runFileConvert = async (signal: AbortSignal): Promise<OutFile[]> => {
    const transcribing = isTranscribing;
    const total = entries.length;

    if (transcribing || total === 1) {
      const results: OutFile[] = [];
      for (let i = 0; i < total; i++) {
        const { file } = entries[i];
        const prefix = total > 1 ? `${i + 1} of ${total} · ` : "";
        if (transcribing) {
          results.push(await runTranscribe(file, prefix, signal));
        } else {
          results.push(await convertOne(file, signal, setStatusLabel));
        }
      }
      return results;
    }

    const results: OutFile[] = new Array(total);
    let next = 0;
    let done = 0;
    setStatusLabel(`converting ${total} files → ${targetLabel}`);

    const worker = async () => {
      for (;;) {
        const i = next++;
        if (i >= total) return;
        // Through the job path, same as a single file: a long conversion
        // must not sit on an open connection waiting to be timed out.
        results[i] = await convertOne(entries[i].file, signal, () => {});
        done += 1;
        setStatusLabel(`${done} of ${total} converted → ${targetLabel}`);
      }
    };

    await Promise.all(
      Array.from({ length: Math.min(3, total) }, worker)
    );
    return results;
  };

  const convert = async () => {
    setError("");
    setPhase("working");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const results =
        mode === "url"
          ? await runUrlConvert(controller.signal)
          : await runFileConvert(controller.signal);
      setOutputs(results);
      setPhase("done");
      results.forEach((r) => triggerDownload(r.url, r.name));
    } catch (err: unknown) {
      if ((err as Error)?.name === "AbortError") {
        setPhase("idle");
        return;
      }
      setError((err as Error)?.message || "Could not reach the local engine.");
      setPhase("idle");
    } finally {
      abortRef.current = null;
    }
  };

  /* Tell the engine too — otherwise the laptop keeps transcribing for a
     result the browser has already walked away from. */
  const cancel = () => {
    for (const job of jobsRef.current) {
      api(`/api/jobs/${job}/cancel`, { method: "POST" }).catch(() => {});
    }
    jobsRef.current.clear();
    abortRef.current?.abort();
  };

  const startOver = () => {
    setEntries([]);
    setMediaUrl("");
    setMaxSize("");
    setOutWidth("");
    setOutHeight("");
    setAdvanced(false);
    resetResult();
  };

  const canConvert =
    phase !== "working" &&
    !badDimension &&
    tooBig.length === 0 &&
    (mode === "url"
      ? mediaUrl.trim().length > 0
      : entries.length > 0 && kind !== "other" && !!target);

  /* Keyboard: Enter converts, Esc cancels. */
  const keyGateRef = useRef({ convert, canConvert, phase });
  keyGateRef.current = { convert, canConvert, phase };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const gate = keyGateRef.current;
      if (e.key === "Escape" && gate.phase === "working") {
        abortRef.current?.abort();
        return;
      }
      if (e.key !== "Enter" || e.repeat) return;
      const el = document.activeElement as HTMLElement | null;
      if (el?.closest("button, a, input, textarea, select")) return;
      if (gate.canConvert && gate.phase !== "done") {
        gate.convert();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /* Engine grid: web-able cells arm the studio, the rest copy their CLI. */
  const engineCopyTimer = useRef(0);
  const onEngineClick = (s: Service) => {
    const webMode = WEB_ABLE[s.id];
    if (webMode) {
      switchMode(webMode);
      cardRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      showToast(
        webMode === "url"
          ? "Studio armed — paste your link"
          : "Studio armed — drop your file"
      );
      return;
    }
    navigator.clipboard?.writeText(s.command).then(() => {
      setCopiedEngine(s.id);
      window.clearTimeout(engineCopyTimer.current);
      engineCopyTimer.current = window.setTimeout(
        () => setCopiedEngine(null),
        2200
      );
    });
  };

  const minutes = Math.floor(elapsed / 60);
  const seconds = String(elapsed % 60).padStart(2, "0");

  /* ── Render ──────────────────────────────────────────────────────────── */

  const SIZE_PRESETS = ["500KB", "1MB", "2MB"];
  /* Longest-edge presets. Only ones that actually shrink the picture are
     offered — "1920" on a 900px photo would upscale it, which nobody wants
     from a control labelled Dimensions. */
  const EDGE_PRESETS = [1920, 1280, 800];

  /* Scale the longest edge to `edge`, leaving the other side blank so the
     engine keeps the aspect ratio rather than us rounding it here. */
  const setLongestEdge = (edge: number) => {
    if (!natural) return;
    if (natural.width >= natural.height) {
      setOutWidth(String(edge));
      setOutHeight("");
    } else {
      setOutHeight(String(edge));
      setOutWidth("");
    }
  };

  const activeEdge = (edge: number) =>
    natural
      ? natural.width >= natural.height
        ? outWidth === String(edge) && !outHeight
        : outHeight === String(edge) && !outWidth
      : false;

  /* An .ico is a bundle of standard icon sizes, so an exact width isn't
     something the format lets us honour. */
  const dimensionsApply = target !== "ico";

  const dimensionControls = () => {
    if (mode !== "file" || kind !== "image" || !dimensionsApply) return null;
    const longest = natural ? Math.max(natural.width, natural.height) : 0;
    return (
      <div className="opt">
        <span className="opt-label">
          Dimensions
          {natural && (
            <span className="opt-note">
              {" "}
              now {natural.width} × {natural.height}
            </span>
          )}
        </span>
        <div className="chips">
          <button
            className={`chip ${!outWidth && !outHeight ? "active" : ""}`}
            onClick={() => {
              setOutWidth("");
              setOutHeight("");
            }}
          >
            original
          </button>
          {EDGE_PRESETS.filter((edge) => edge < longest).map((edge) => (
            <button
              key={edge}
              className={`chip ${activeEdge(edge) ? "active" : ""}`}
              onClick={() => setLongestEdge(edge)}
              title={`Longest side ${edge} px, aspect ratio kept`}
            >
              {edge} px
            </button>
          ))}
          <span className="dim-pair">
            <input
              className="size-input dim-input"
              type="text"
              inputMode="numeric"
              placeholder="width"
              value={outWidth}
              onChange={(e) => setOutWidth(e.target.value)}
              aria-label="Output width in pixels"
            />
            <span className="dim-times" aria-hidden="true">
              ×
            </span>
            <input
              className="size-input dim-input"
              type="text"
              inputMode="numeric"
              placeholder="height"
              value={outHeight}
              onChange={(e) => setOutHeight(e.target.value)}
              aria-label="Output height in pixels"
            />
          </span>
        </div>
        {badDimension ? (
          <span className="chip-divider">
            width and height are whole pixels, 1 to 20000
          </span>
        ) : (
          (outWidth || outHeight) &&
          !(outWidth && outHeight) && (
            <span className="chip-divider">
              the other side follows, so the picture keeps its shape
            </span>
          )
        )}
      </div>
    );
  };

  /* Images are the one kind where people arrive with a number in mind — an
     upload limit — rather than a format. */
  const sizeControls = () => {
    if (mode !== "file" || kind !== "image") return null;
    const custom = SIZE_PRESETS.includes(maxSize) ? "" : maxSize;
    return (
      <div className="opt">
        <span className="opt-label">Maximum size</span>
        <div className="chips">
          <button
            className={`chip ${!maxSize ? "active" : ""}`}
            onClick={() => setMaxSize("")}
          >
            no limit
          </button>
          {SIZE_PRESETS.map((preset) => (
            <button
              key={preset}
              className={`chip ${maxSize === preset ? "active" : ""}`}
              onClick={() => setMaxSize(preset)}
            >
              {preset.replace(/(KB|MB)/, " $1")}
            </button>
          ))}
          <input
            className="size-input"
            type="text"
            placeholder="or 800KB"
            value={custom}
            onChange={(e) => setMaxSize(e.target.value)}
            aria-label="Custom maximum file size"
          />
        </div>
        {maxSize.trim() && !maxBytes && (
          <span className="chip-divider">
            that isn&apos;t a size — try 500KB, 1.5MB, 900k
          </span>
        )}
        {maxBytes !== null && (
          <span className="chip-divider">
            quality goes before pixels — the picture keeps its size on screen
            unless the budget leaves no other way
          </span>
        )}
      </div>
    );
  };

  /* What the refinements currently add up to, so folding them away never
     hides a setting that is doing something. */
  const optionSummary = () => {
    const bits: string[] = [];
    if (outWidth && outHeight) bits.push(`${outWidth} × ${outHeight}`);
    else if (outWidth) bits.push(`${outWidth} px wide`);
    else if (outHeight) bits.push(`${outHeight} px tall`);
    if (maxBytes) bits.push(`max ${maxSize.replace(/(KB|MB)/, " $1")}`);
    return bits.join(" · ");
  };

  /* Refinements for the file in hand. Images are the only kind with any so
     far, so for everything else the drawer isn't there at all rather than
     opening onto nothing. */
  const moreOptions = () => {
    if (mode !== "file" || kind !== "image") return null;
    const summary = optionSummary();
    return (
      <div className="more">
        <button
          className={`more-toggle ${advanced ? "open" : ""}`}
          onClick={() => setAdvanced((v) => !v)}
          aria-expanded={advanced}
        >
          <span className="more-sign" aria-hidden="true">
            {advanced ? "−" : "+"}
          </span>
          {advanced ? "Fewer options" : "More options"}
          {!advanced && summary && <span className="more-summary">{summary}</span>}
        </button>
        {advanced && (
          <div className="more-body">
            {dimensionControls()}
            {sizeControls()}
            {target === "ico" && (
              <span className="chip-divider">
                an .ico holds a standard set of icon sizes, so its dimensions
                aren&apos;t ours to choose
              </span>
            )}
          </div>
        )}
      </div>
    );
  };

  const targetChips = () => {
    if (mode === "url") {
      return (
        <div className="opt">
          <span className="opt-label">Save as</span>
          <div className="chips">
            {URL_TARGETS.map((fmt) => (
              <button
                key={fmt}
                className={`chip ${target === fmt ? "active" : ""}`}
                onClick={() => setTarget(fmt)}
              >
                .{fmt}
              </button>
            ))}
          </div>
        </div>
      );
    }
    if (!kind || kind === "other" || !engineHandles(kind)) return null;
    const opts = TARGETS[kind];
    return (
      <div className="opt">
        <span className="opt-label">Convert to</span>
        <div className="chips">
          {maxBytes && (
            <button
              className={`chip ${target === "auto" ? "active" : ""}`}
              onClick={() => setTarget("auto")}
              title="Keep the format when it fits the budget — and re-encode rather than shrink the picture when it doesn't"
            >
              best fit
            </button>
          )}
          {opts.main
            /* Converting a file to what it already is does nothing — unless
               the point is the size, in which case it does. */
            .filter((fmt) => maxBytes !== null || fmt !== sourceExt)
            .map((fmt) => (
            <button
              key={fmt}
              className={`chip ${target === fmt ? "active" : ""}`}
              onClick={() => setTarget(fmt)}
            >
              .{fmt}
            </button>
          ))}
          {opts.audio && (
            <>
              <span className="chip-divider">audio only</span>
              {opts.audio.map((fmt) => (
                <button
                  key={fmt}
                  className={`chip ${target === fmt ? "active" : ""}`}
                  onClick={() => setTarget(fmt)}
                >
                  .{fmt}
                </button>
              ))}
            </>
          )}
          {opts.text && canTranscribe && (
            <>
              <span className="chip-divider">transcribe</span>
              {opts.text.map((fmt) => (
                <button
                  key={fmt}
                  className={`chip ${target === fmt ? "active" : ""}`}
                  onClick={() => setTarget(fmt)}
                  title="Whisper, running on the engine"
                >
                  .{fmt}
                </button>
              ))}
            </>
          )}
          {opts.text && !canTranscribe && engineOnline && (
            <span className="chip-divider">
              transcription needs the local studio
            </span>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="page">
      <CleanHeroBackground />

      {globalDrag && (
        <div className="drop-veil" aria-hidden="true">
          <div className="veil-frame">
            <div className="veil-title">Drop it anywhere</div>
            <div className="veil-sub">audio · video · images</div>
          </div>
        </div>
      )}

      {toast && (
        <div className="toast" key={toast.id} role="status">
          {toast.msg}
        </div>
      )}

      <header className="site-head shell reveal d0">
        <a className="wordmark" href="#top">
          Transcripe<span className="dot">.</span>
        </a>
        <nav className="site-nav">
          <button
            className="theme-toggle"
            onClick={() => {
              const next: Theme = theme === "dark" ? "light" : "dark";
              applyTheme(next);
              setTheme(next);
            }}
            aria-label={theme === "dark" ? "Switch to light" : "Switch to dark"}
            title={theme === "dark" ? "Lights on" : "Lights low"}
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <a className="nav-link" href="#engines">
            Engines
          </a>
          <a
            className="nav-link"
            href="https://github.com/abdulrahmanJAlabbed/Transcripe"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
          <button
            className={`pip-chip ${pipCopied ? "copied" : ""}`}
            onClick={() => copyPip("pip install transcripe")}
          >
            {pipCopied ? "copied ✓" : "$ pip install transcripe"}
          </button>
        </nav>
      </header>

      <main>
        <section className="hero shell" id="top">
          <div className="hero-orb" aria-hidden="true">
            <Orb
              hue={0}
              hoverIntensity={0.5}
              rotateOnHover
              forceHoverState={false}
              backgroundColor={theme === "dark" ? "#121316" : "#f7f7f9"}
            />
          </div>

          <p className="eyebrow reveal d1">
            {HOSTED ? "Live demo · Open source" : "Local · Private · Open source"}
          </p>
          <h1 className="reveal d2">
            Every file, <em>quietly</em> transformed.
          </h1>
          <p className="lede reveal d3">
            {HOSTED
              ? "Transcribe a lecture, pull a reel, convert anything — try it here, then install it so your files never leave your machine."
              : "Transcribe a lecture, pull a reel, convert anything — sixteen engines that run on your machine and answer to no cloud."}
          </p>

          <div className="card reveal d4" ref={cardRef}>
            <div className="seg" data-mode={mode} role="tablist">
              <span className="seg-thumb" aria-hidden="true" />
              <button
                role="tab"
                aria-selected={mode === "file"}
                onClick={() => switchMode("file")}
              >
                Upload files
              </button>
              <button
                role="tab"
                aria-selected={mode === "url"}
                onClick={() => switchMode("url")}
              >
                From a link
              </button>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={onFileInput}
              style={{ display: "none" }}
            />

            {mode === "file" ? (
              <div className="panel" key="file">
                {entries.length === 0 ? (
                  <div
                    className={`dropzone ${isDragging ? "is-dragging" : ""}`}
                    onClick={() => fileInputRef.current?.click()}
                    onKeyDown={(e) =>
                      e.key === "Enter" && fileInputRef.current?.click()
                    }
                    role="button"
                    tabIndex={0}
                    aria-label="Add files to convert"
                    {...dragProps}
                  >
                    <span className="drop-plus">
                      <Plus size={20} strokeWidth={1.8} />
                    </span>
                    <div>
                      <div className="drop-title">Drop files here</div>
                      <div className="drop-sub">or click to browse — audio, video, images</div>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="file-stack">
                      {entries.map((entry) => (
                        <div className="file-row" key={entry.id}>
                          <span className="ext-badge">{entry.ext || "file"}</span>
                          <span className="file-name">{entry.file.name}</span>
                          <span className="file-size">
                            {formatBytes(entry.file.size)}
                          </span>
                          <button
                            className="row-x"
                            onClick={() => removeEntry(entry.id)}
                            aria-label={`Remove ${entry.file.name}`}
                          >
                            <X size={14} />
                          </button>
                        </div>
                      ))}
                    </div>

                    <button
                      className={`add-more ${isDragging ? "is-dragging" : ""}`}
                      onClick={() => fileInputRef.current?.click()}
                      {...dragProps}
                    >
                      <Plus size={14} /> Add more files
                    </button>

                    {tooBig.length > 0 && (
                      <div className="offline-chip" role="status">
                        <span>
                          {tooBig.length === 1
                            ? `${tooBig[0].file.name} is ${formatBytes(
                                tooBig[0].file.size
                              )} — this engine accepts up to ${maxUploadMb} MB`
                            : `${tooBig.length} files are over this engine's ${maxUploadMb} MB limit`}
                          . Run the studio on your own machine and the limit is
                          yours to set.
                        </span>
                      </div>
                    )}

                    {strays.length > 0 && (
                      <div className="offline-chip" role="status">
                        <span>
                          {strays.length === 1
                            ? `${strays[0].file.name} isn't the same kind of file as the rest`
                            : `${strays.length} files aren't the same kind as the rest`}{" "}
                          — one target applies to the whole batch, so convert
                          them separately.
                        </span>
                      </div>
                    )}

                    {cliService ? (
                      <div className="cli-hint">
                        <span className="cli-hint-title">
                          {cliService.title} lives in the CLI
                        </span>
                        <span className="cli-hint-note">
                          .{entries[0].ext} isn&apos;t handled in the browser yet —
                          this one-liner does it locally:
                        </span>
                        <div className="cmd-line">
                          <code>
                            {personalize(cliService.command, entries[0].file.name)}
                          </code>
                          <button
                            className={`cmd-copy ${cmdCopied ? "copied" : ""}`}
                            onClick={() =>
                              copyCmd(
                                personalize(
                                  cliService.command,
                                  entries[0].file.name
                                )
                              )
                            }
                            aria-label="Copy command"
                          >
                            {cmdCopied ? <Check size={13} /> : <Copy size={13} />}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        {targetChips()}
                        {moreOptions()}
                      </>
                    )}
                  </>
                )}
              </div>
            ) : (
              <div className="panel" key="url">
                <div className="url-wrap">
                  <input
                    className="url-input"
                    type="url"
                    placeholder="Paste a link — YouTube, Instagram, TikTok, X…"
                    value={mediaUrl}
                    onChange={(e) => {
                      setMediaUrl(e.target.value);
                      if (phase === "done") resetResult();
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && canConvert) convert();
                    }}
                  />
                  <button className="paste-btn" onClick={pasteFromClipboard}>
                    <Clipboard size={13} /> Paste
                  </button>
                </div>

                {platform ? (
                  <div className="detect">{platform} detected</div>
                ) : (
                  <p className="hint">
                    Works with 1,000+ sites — reels without watermarks, shorts,
                    clips, full tracks.
                  </p>
                )}

                {mediaUrl.trim() && (
                  <>
                    {targetChips()}
                    {!TEXT_TARGETS.includes(target) && target !== "mp3" && (
                      <div className="opt">
                        <span className="opt-label">Quality</span>
                        <div className="chips">
                          <button
                            className={`chip ${linkQuality === "best" ? "active" : ""}`}
                            onClick={() => setLinkQuality("best")}
                            title="Highest resolution available, up to 4K"
                          >
                            best available
                          </button>
                          <button
                            className={`chip ${linkQuality === "compatible" ? "active" : ""}`}
                            onClick={() => setLinkQuality("compatible")}
                            title="H.264 for older players — YouTube caps this at 1080p"
                          >
                            most compatible
                          </button>
                        </div>
                      </div>
                    )}

                    <label className="check-row">
                      <input
                        type="checkbox"
                        checked={useCookies}
                        onChange={(e) => setUseCookies(e.target.checked)}
                      />
                      Use my browser&apos;s cookies for private or age-gated links
                      — never stored
                    </label>
                  </>
                )}
              </div>
            )}

            {engineOnline === false && (
              <div className="offline-chip" role="status">
                <span>
                  Local engine is offline — start it with{" "}
                  <code>transcripe studio</code>
                </span>
                <button
                  onClick={() => copyOffline("transcripe studio")}
                  aria-label="Copy start command"
                >
                  {offlineCopied ? <Check size={13} /> : <Copy size={13} />}
                </button>
              </div>
            )}

            {engineOnline && engineLocked && (
              <div className="offline-chip" role="status">
                <span>
                  This studio is open to the network, so it needs its token —
                  paste the one it printed on startup.
                </span>
                <input
                  className="token-input"
                  type="password"
                  placeholder="token"
                  onChange={(e) => setToken(e.target.value)}
                  aria-label="Studio token"
                />
              </div>
            )}

            {error && (
              <div className="err-banner" role="alert">
                <span>{error}</span>
                <button onClick={() => setError("")} aria-label="Dismiss">
                  <X size={14} />
                </button>
              </div>
            )}

            {phase === "working" ? (
              <div className="working">
                <div className="working-row">
                  <span className="working-label">{statusLabel}</span>
                  <span className="working-time">
                    {minutes}:{seconds}
                  </span>
                </div>
                <div className="track">
                  <div className="track-slide" />
                </div>
                <button className="cancel-btn" onClick={cancel}>
                  Cancel
                </button>
              </div>
            ) : phase === "done" && outputs.length > 0 ? (
              <div className="done">
                <div className="done-row">
                  <span className="done-check">
                    <svg
                      width="15"
                      height="15"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M4 12.5l5.5 5.5L20 6.5" />
                    </svg>
                  </span>
                  <div className="done-text">
                    <div className="done-title">{outputs[0].name}</div>
                    <div className="done-sub">
                      {outputs.length > 1
                        ? `and ${outputs.length - 1} more — downloads started`
                        : "download started"}
                    </div>
                  </div>
                </div>
                <div className="done-actions">
                  <button
                    className="ghost accent"
                    onClick={() =>
                      outputs.forEach((o) => triggerDownload(o.url, o.name))
                    }
                  >
                    <Download size={15} /> Save again
                  </button>
                  <button className="ghost" onClick={startOver}>
                    <RotateCcw size={14} /> Convert another
                  </button>
                </div>
              </div>
            ) : (
              <button className="cta" disabled={!canConvert} onClick={convert}>
                {mode === "url"
                  ? `Fetch & convert${target ? ` to .${target}` : ""}`
                  : kind === "other"
                  ? "Use the CLI for this format"
                  : !engineHandles(kind)
                  ? "This engine has no spreadsheet support"
                  : isTranscribing
                  ? `Transcribe to .${target}`
                  : `Convert${target ? ` to ${targetLabel}` : ""}`}
                <ArrowRight className="arrow" size={17} />
              </button>
            )}
          </div>

          <LiveStats online={engineOnline} />

          <p className="trust reveal d5">
            {localCount > 0 ? (
              <>
                <b>{localCount}</b>{" "}
                {localCount === 1 ? "file" : "files"} converted{" "}
                <b>on this device</b> · never uploaded anywhere
              </>
            ) : HOSTED ? (
              <>
                images convert in your browser · everything else on the server ·{" "}
                <b>deleted right after</b>
              </>
            ) : (
              <>
                processed in memory · streamed back · <b>deleted immediately</b>
              </>
            )}
          </p>
        </section>

        <section className="engines shell" id="engines">
          <div className="sec-head" data-reveal>
            <h2>
              Sixteen engines, <em>one</em> keystroke each.
            </h2>
            <p>
              The studio above handles media, images, links, and Whisper
              transcription. Everything here ships in the CLI — same machine,
              same privacy, more muscle.
            </p>
          </div>

          <div className="engine-grid" data-reveal>
            {services.map((s) => {
              const Icon = s.icon;
              const webMode = WEB_ABLE[s.id];
              return (
                <button
                  className="engine-cell"
                  key={s.id}
                  onClick={() => onEngineClick(s)}
                  title={
                    webMode
                      ? "Open in the studio above"
                      : "Click to copy the CLI command"
                  }
                >
                  <div className="engine-top">
                    <Icon size={17} strokeWidth={1.8} />
                    <span className="engine-cat">{s.category}</span>
                  </div>
                  <div className="engine-title">{s.title}</div>
                  <p className="engine-sum">{s.summary}</p>
                  <div className="engine-io">
                    {copiedEngine === s.id ? (
                      <span className="io-copied">
                        ✓ copied — paste in a terminal
                      </span>
                    ) : (
                      <>
                        {s.inputs.slice(0, 3).join(" ")}
                        {s.inputs.length > 3 ? ` +${s.inputs.length - 3}` : ""}
                        <span className="io-arrow">→</span>
                        {s.outputs.slice(0, 3).join(" ")}
                        {s.outputs.length > 3
                          ? ` +${s.outputs.length - 3}`
                          : ""}
                      </>
                    )}
                  </div>
                </button>
              );
            })}
            <a
              className="engine-cell more"
              href="https://github.com/abdulrahmanJAlabbed/Transcripe/issues"
              target="_blank"
              rel="noreferrer"
            >
              <div className="engine-title">Missing a format? →</div>
              <p className="engine-sum">
                Open an issue and it&apos;ll likely land as engine seventeen.
              </p>
            </a>
          </div>
        </section>

        <div className="marquee" aria-hidden="true">
          <div className="marquee-track">
            {[...FORMAT_TICKER, ...FORMAT_TICKER].map((fmt, i) => (
              <span className="marquee-item" key={`${fmt}-${i}`}>
                {fmt}
              </span>
            ))}
          </div>
        </div>

        <section className="pocket shell" id="app">
          <div className="pocket-copy" data-reveal>
            <h2>
              Take it <em>with you</em>.
            </h2>
            <p>
              The phone app picks a video or a link and hands it to the engine
              on your laptop. Same design, same privacy — your files stay on
              your own Wi-Fi.
            </p>
            <div className="store-row">
              <a
                className="store-btn"
                href={APP_QR_TARGET}
                target="_blank"
                rel="noreferrer"
              >
                <Apple size={20} strokeWidth={1.6} />
                <span>
                  <small>Run it on</small>
                  iPhone
                </span>
              </a>
              <a
                className="store-btn"
                href={APP_QR_TARGET}
                target="_blank"
                rel="noreferrer"
              >
                <Smartphone size={20} strokeWidth={1.6} />
                <span>
                  <small>Run it on</small>
                  Android
                </span>
              </a>
            </div>
            <p className="pocket-note">
              Both open in <b>Expo Go</b> — no store account, no sideloading.
            </p>
          </div>

          <div className="pocket-qr" data-reveal data-reveal-delay="120">
            <div className="qr-frame" dangerouslySetInnerHTML={{ __html: appQr }} />
            <span className="qr-cap">scan to set it up</span>
          </div>
        </section>

        <section className="cli-band shell">
          <div className="term" data-reveal ref={spotlightRef}>
            <button
              className={`term-copy ${termCopied ? "copied" : ""}`}
              onClick={() => copyTerm("pip install transcripe")}
            >
              {termCopied ? <Check size={12} /> : <Copy size={12} />}
              {termCopied ? "copied" : "copy"}
            </button>
            <div className="term-lines">
              <span>
                <span className="c"># the whole studio, one install</span>
              </span>
              <span>
                <span className="p">$ </span>pip install transcripe
              </span>
              <span>
                <span className="p">$ </span>transcripe media transcribe
                lecture.mp4 --srt
              </span>
              <span>
                <span className="p">$ </span>transcripe download
                https://instagram.com/reel/… --to mp4
              </span>
            </div>
          </div>
          <p className="cli-caption">
            Batch folders, watch modes, language packs —{" "}
            <a
              href="https://github.com/abdulrahmanJAlabbed/Transcripe"
              target="_blank"
              rel="noreferrer"
            >
              the README has the full tour
            </a>
            .
          </p>
        </section>
      </main>

      <footer className="site-foot">
        <div className="foot-inner shell">
          <span className="foot-brand">Transcripe.</span>
          <span>Runs where your files live.</span>
          <nav className="foot-links">
            <a
              href="https://github.com/abdulrahmanJAlabbed/Transcripe"
              target="_blank"
              rel="noreferrer"
            >
              GitHub
            </a>
            <a
              href="https://pypi.org/project/transcripe/"
              target="_blank"
              rel="noreferrer"
            >
              PyPI
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}

export default App;
