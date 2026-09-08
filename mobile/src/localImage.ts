/**
 * Image work done on the phone itself.
 *
 * The laptop is not the only machine in the room. A phone re-encodes a photo
 * natively in well under a second, and doing it here means the picture never
 * crosses the Wi-Fi to be made smaller — which is the point, since the reason
 * to shrink a photo is usually that it is about to be uploaded somewhere.
 *
 * It also sidesteps the engine's upload ceiling entirely: a 40 MB photo that
 * the server would refuse is nothing to the device that took it.
 *
 * Same ladder as the browser and the engine: spend quality before pixels, and
 * leave a lossless format only when keeping it would mean shrinking the
 * picture. Anything this can't do throws, and the caller falls back to the
 * engine — a slower answer beats no answer.
 */
import { File } from "expo-file-system";
import { manipulateAsync, SaveFormat } from "expo-image-manipulator";

const QUALITY_CEILING = 0.95;
const QUALITY_FLOOR = 0.55;

/** Formats the phone can write. It reads more than it writes — HEIC comes in
 *  and leaves as JPEG, which is what anyone wants from it anyway. */
const WRITABLE: Record<string, SaveFormat> = {
  jpg: SaveFormat.JPEG,
  jpeg: SaveFormat.JPEG,
  png: SaveFormat.PNG,
  webp: SaveFormat.WEBP
};

/** What both phone platforms decode without help. */
const READABLE = ["jpg", "jpeg", "png", "heic", "heif", "webp", "gif", "bmp"];

/** Only JPEG and WebP have a quality dial; PNG can shed nothing but pixels. */
const HAS_QUALITY = ["jpg", "jpeg", "webp"];

export type LocalImage = {
  uri: string;
  name: string;
  width: number;
  height: number;
  size: number;
};

export function canProcessLocally(sourceExt: string, target: string): boolean {
  const from = sourceExt.toLowerCase();
  return READABLE.includes(from) && (target === "auto" || target in WRITABLE);
}

type Attempt = { uri: string; width: number; height: number; size: number };

async function encode(
  uri: string,
  ext: string,
  quality: number,
  resize?: { width?: number; height?: number }
): Promise<Attempt> {
  const actions = resize ? [{ resize }] : [];
  const res = await manipulateAsync(uri, actions, {
    compress: quality,
    format: WRITABLE[ext]
  });
  let size = 0;
  try {
    size = new File(res.uri).size ?? 0;
  } catch {
    size = 0;
  }
  return { uri: res.uri, width: res.width, height: res.height, size };
}

/** Throw away an attempt that lost, so a search doesn't fill the cache. */
function discard(attempt: Attempt | null, keep: string) {
  if (!attempt || attempt.uri === keep) return;
  try {
    new File(attempt.uri).delete();
  } catch {
    /* the cache prune will get it */
  }
}

/** Highest quality that still fits, by binary search — seven encodes cover
 *  the range and the answer lands just under the budget, not far below it. */
async function bestUnder(
  uri: string,
  ext: string,
  limit: number,
  resize?: { width?: number; height?: number }
): Promise<{ attempt: Attempt; quality: number } | null> {
  let lo = 20;
  let hi = Math.round(QUALITY_CEILING * 100);
  let best: { attempt: Attempt; quality: number } | null = null;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const attempt = await encode(uri, ext, mid / 100, resize);
    if (attempt.size && attempt.size <= limit) {
      discard(best?.attempt ?? null, attempt.uri);
      best = { attempt, quality: mid / 100 };
      lo = mid + 1;
    } else {
      discard(attempt, best?.attempt.uri ?? "");
      hi = mid - 1;
    }
  }
  return best;
}

export async function processLocally(
  input: { uri: string; name: string; ext: string },
  opts: { target: string; maxBytes?: number | null; width?: number | null }
): Promise<LocalImage> {
  const from = input.ext.toLowerCase();
  const resize = opts.width ? { width: opts.width } : undefined;

  let ext = opts.target === "auto" ? (from === "jpeg" ? "jpg" : from) : opts.target;
  if (!(ext in WRITABLE)) ext = "jpg"; // heic and friends leave as JPEG
  const named = (e: string) => `${input.name.replace(/\.[^.]+$/, "")}.${e}`;

  // No budget: one encode at the top of the dial and we're done.
  if (!opts.maxBytes) {
    const done = await encode(input.uri, ext, QUALITY_CEILING, resize);
    if (!done.size) throw new Error("the phone produced nothing");
    return { ...done, name: named(ext) };
  }

  const limit = opts.maxBytes;

  // A format with no quality dial can only meet a budget by losing pixels, so
  // when it doesn't already fit, move to one that can.
  if (!HAS_QUALITY.includes(ext)) {
    const asIs = await encode(input.uri, ext, 1, resize);
    if (asIs.size && asIs.size <= limit) return { ...asIs, name: named(ext) };
    discard(asIs, "");
    if (opts.target === "auto") ext = "jpg";
  }

  if (HAS_QUALITY.includes(ext)) {
    const full = await bestUnder(input.uri, ext, limit, resize);
    if (full && full.quality >= QUALITY_FLOOR) {
      return { ...full.attempt, name: named(ext) };
    }
    // Out of quality — start removing pixels, solving for the scale rather
    // than stepping blindly toward it.
    const probe = full?.attempt ?? (await encode(input.uri, ext, QUALITY_FLOOR, resize));
    let width = probe.width;
    for (let attempt = 0; attempt < 6; attempt++) {
      const shrink = Math.sqrt(limit / Math.max(probe.size, 1)) * 0.95;
      width = Math.max(16, Math.round(width * Math.min(1, shrink) * (attempt ? 0.85 : 1)));
      const got = await bestUnder(input.uri, ext, limit, { width });
      if (got) {
        discard(probe, got.attempt.uri);
        return { ...got.attempt, name: named(ext) };
      }
      if (width <= 16) break;
    }
    if (full) return { ...full.attempt, name: named(ext) };
  }

  throw new Error("this file needs the engine");
}
