/** Format + platform knowledge, ported from the web studio. */

export const AUDIO_EXTS = ["mp3", "wav", "m4a", "flac", "aac", "ogg", "opus", "wma", "aiff", "alac"];
export const VIDEO_EXTS = ["mp4", "mkv", "mov", "webm", "avi", "3gp", "flv", "wmv", "m4v", "mpg", "mpeg", "ts"];
export const IMAGE_EXTS = ["png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif", "heic", "heif", "avif", "ico"];
export const SUBTITLE_EXTS = ["srt", "vtt", "ass", "ssa"];
export const DATA_EXTS = ["csv", "json", "yaml", "yml", "xml", "xlsx", "tsv", "parquet", "toml"];

export type Kind = "audio" | "video" | "image" | "subtitle" | "data" | "other";

export function kindOf(ext: string): Kind {
  const e = ext.toLowerCase();
  if (AUDIO_EXTS.includes(e)) return "audio";
  if (VIDEO_EXTS.includes(e)) return "video";
  if (IMAGE_EXTS.includes(e)) return "image";
  if (SUBTITLE_EXTS.includes(e)) return "subtitle";
  if (DATA_EXTS.includes(e)) return "data";
  return "other";
}

/** `text` targets go to Whisper on the engine rather than ffmpeg. */
export const TARGETS: Record<
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

export const TEXT_TARGETS = ["srt", "txt"];

export const URL_TARGETS = ["mp4", "mp3", "m4a", "wav", "flac"];

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

export function detectPlatform(url: string): string | null {
  const lower = url.trim().toLowerCase();
  if (!lower) return null;
  for (const [hosts, name] of PLATFORMS) {
    if (hosts.some((h) => lower.includes(h))) return name;
  }
  return lower.startsWith("http") ? "direct link" : null;
}

export function extOf(name: string): string {
  const parts = name.split("?")[0].split(".");
  return parts.length > 1 ? parts.pop()!.toLowerCase() : "";
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${(bytes / 1_073_741_824).toFixed(2)} GB`;
}

/** "500KB", "2 MB", "500k", "512000" → bytes. Mirrors engines/images.py. */
export function parseSize(text: string): number | null {
  const s = String(text).trim().toUpperCase().replace(/\s+/g, "");
  const m = s.match(/^([\d.]+)(KB|K|MB|M|GB|G|B)?$/);
  if (!m) return null;
  const n = parseFloat(m[1]);
  if (!isFinite(n) || n <= 0) return null;
  const mult =
    { KB: 1024, K: 1024, MB: 1024 ** 2, M: 1024 ** 2, GB: 1024 ** 3, G: 1024 ** 3, B: 1 }[
      m[2] ?? "B"
    ] ?? 1;
  return Math.round(n * mult);
}

export const SIZE_PRESETS = ["500KB", "1MB", "2MB"];

/** Longest-edge presets, in pixels. Only ones smaller than the picture
 *  are worth offering — the rest would upscale it. */
export const EDGE_PRESETS = ["1920", "1280", "800"];

export function firstUrl(text: string): string | null {
  return text.match(/https?:\/\/\S+/i)?.[0] ?? null;
}
