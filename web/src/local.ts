/**
 * Conversions the visitor's own machine can do.
 *
 * The browser is not a poor relation of the engine here — on this hardware it
 * encodes 720p H.264 at ~350 fps through WebCodecs, comfortably faster than a
 * small server, and the file never leaves the device. So: try locally first,
 * fall back to the engine when the browser can't (HEIC decoding in Chrome, mp3
 * encoding, link downloads, Whisper).
 */

const IMAGE_OUT: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp"
};

/* Formats every engine-capable browser can decode. HEIC is deliberately absent:
   only Safari decodes it, so it goes to the engine where Pillow handles it. */
const IMAGE_IN = ["png", "jpg", "jpeg", "webp", "gif", "bmp"];

export type LocalResult = { blob: Blob; name: string };

/** Pixel dimensions asked for. Either one alone scales the other to match, so
 *  a caller who knows only "1280 wide" doesn't have to do the arithmetic. */
export type Dimensions = { width?: number | null; height?: number | null };

function sizedTo(
  natural: { width: number; height: number },
  dims?: Dimensions
): [number, number] {
  const w = dims?.width ?? null;
  const h = dims?.height ?? null;
  if (w && h) return [w, h];
  if (w) return [w, Math.max(1, Math.round(natural.height * (w / natural.width)))];
  if (h) return [Math.max(1, Math.round(natural.width * (h / natural.height))), h];
  return [natural.width, natural.height];
}

/* ── Video, in the page ───────────────────────────────────────────────────
   Mediabunny drives WebCodecs, which is hardware-backed: measured here at
   ~350 fps for 720p H.264. It copies streams when the container can hold
   them, so a container change is lossless and costs almost nothing — and the
   file never leaves the machine. */

const VIDEO_OUT = ["mp4", "webm", "mkv"];
const VIDEO_IN = ["mp4", "webm", "mkv", "mov", "m4v"];

export function canConvertVideoLocally(sourceExt: string, target: string): boolean {
  if (typeof VideoEncoder === "undefined" || typeof VideoDecoder === "undefined") {
    return false;
  }
  return (
    VIDEO_IN.includes(sourceExt.toLowerCase()) && VIDEO_OUT.includes(target)
  );
}

export async function convertVideoLocally(
  file: File,
  target: string,
  onProgress?: (fraction: number) => void
): Promise<LocalResult> {
  const {
    Input,
    Output,
    Conversion,
    BlobSource,
    BufferTarget,
    Mp4OutputFormat,
    WebMOutputFormat,
    MkvOutputFormat,
    ALL_FORMATS
  } = await import("mediabunny");

  const format =
    target === "webm"
      ? new WebMOutputFormat()
      : target === "mkv"
      ? new MkvOutputFormat()
      : new Mp4OutputFormat();

  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
  const output = new Output({ format, target: new BufferTarget() });
  const conversion = await Conversion.init({ input, output });

  // Some tracks can't live in the target container; rather than silently drop
  // them, hand the job to the engine, which can re-encode properly.
  if (!conversion.isValid || conversion.discardedTracks.length > 0) {
    throw new Error("this file needs the engine");
  }
  if (onProgress) conversion.onProgress = (p: number) => onProgress(p);

  await conversion.execute();
  const buffer = output.target.buffer;
  if (!buffer) throw new Error("conversion produced nothing");

  return {
    blob: new Blob([buffer], { type: `video/${target}` }),
    name: `${file.name.replace(/\.[^.]+$/, "")}.${target}`
  };
}

export function canConvertLocally(sourceExt: string, target: string): boolean {
  if (typeof createImageBitmap === "undefined") return false;
  if (typeof OffscreenCanvas === "undefined") return false;
  return IMAGE_IN.includes(sourceExt.toLowerCase()) && target in IMAGE_OUT;
}

/* Sources that arrived without generation loss. Re-compressing one of these
   into a lossy target would throw away detail for nothing. */
const LOSSLESS_SOURCES = ["png", "bmp", "gif", "webp", "tif", "tiff"];

/** Encoder quality, matched to the engine's policy so both paths produce the
 *  same picture. Measured in Chrome: WebP at 1.0 is bit-exact (zero pixel
 *  error), 0.95 is not; PNG is always lossless. */
function encodeQuality(sourceExt: string, target: string): number {
  if (target === "png") return 1;
  if (target === "webp" && LOSSLESS_SOURCES.includes(sourceExt.toLowerCase())) {
    return 1; // lossless WebP
  }
  return 0.95;
}

/** Decode → repaint → re-encode, all in the page. Throws if the browser can't
 *  read the file, which is the caller's cue to fall back to the engine. */
export async function convertImageLocally(
  file: File,
  target: string,
  dims?: Dimensions
): Promise<LocalResult> {
  const type = IMAGE_OUT[target];
  if (!type) throw new Error(`no local encoder for .${target}`);

  // createImageBitmap honours the EXIF orientation tag, so a portrait phone
  // photo comes out upright — same as the engine does with exif_transpose.
  const bitmap = await createImageBitmap(file);
  try {
    const [outW, outH] = sizedTo(bitmap, dims);
    const canvas = new OffscreenCanvas(outW, outH);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no 2d context");

    // JPEG has no alpha; without this, transparent pixels come out black.
    if (type === "image/jpeg") {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
    ctx.drawImage(bitmap, 0, 0, outW, outH);

    const quality = encodeQuality(extensionOf(file.name), target);
    const blob = await canvas.convertToBlob({ type, quality });
    if (!blob || blob.size === 0) throw new Error("encoder produced nothing");
    return {
      blob,
      name: `${file.name.replace(/\.[^.]+$/, "")}.${target}`
    };
  } finally {
    bitmap.close();
  }
}

function extensionOf(name: string): string {
  const parts = name.split("?")[0].split(".");
  return parts.length > 1 ? parts.pop()!.toLowerCase() : "";
}

/* ── Fitting a size budget, in the page ───────────────────────────────────
   Same ladder as the engine: spend quality before resolution, and only leave
   a lossless format when keeping it would mean shrinking the picture. Doing
   it here matters more than for a plain convert — the whole point of "make
   this photo fit 500 KB" is usually that it is about to be uploaded, and this
   way the original never leaves the machine to get there. */

const QUALITY_FLOOR = 0.55;
const QUALITY_CEILING = 0.95;

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

/* Formats with no quality dial: held to a budget they can only shed pixels.
   WebP and AVIF are absent on purpose — they compress, so they stay. Mirrors
   LOSSY_FORMATS in engines/images.py, from the other side. */
const NO_QUALITY_DIAL = ["png", "bmp", "gif", "tif", "tiff"];

export function canFitLocally(sourceExt: string, target: string): boolean {
  if (typeof createImageBitmap === "undefined") return false;
  if (typeof OffscreenCanvas === "undefined") return false;
  if (!IMAGE_IN.includes(sourceExt.toLowerCase())) return false;
  return target === "auto" || target === "jpg" || target === "jpeg" ||
    target === "webp" || target === "png";
}

function draw(bitmap: ImageBitmap, width: number, height: number, opaque: boolean) {
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  if (opaque) {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
  }
  ctx.drawImage(bitmap, 0, 0, width, height);
  return canvas;
}

/** Any non-opaque pixel? Sampled small — this only decides jpeg vs webp. */
function hasAlpha(bitmap: ImageBitmap): boolean {
  const w = Math.min(64, bitmap.width);
  const h = Math.min(64, bitmap.height);
  const ctx = new OffscreenCanvas(w, h).getContext("2d");
  if (!ctx) return false;
  ctx.drawImage(bitmap, 0, 0, w, h);
  const { data } = ctx.getImageData(0, 0, w, h);
  for (let i = 3; i < data.length; i += 4) if (data[i] < 255) return true;
  return false;
}

/** Largest quality whose encode fits, by binary search — seven encodes cover
 *  the range and the result lands just under the budget, not far below it. */
async function bestUnder(
  canvas: OffscreenCanvas,
  type: string,
  limit: number
): Promise<{ blob: Blob; quality: number } | null> {
  let lo = 20;
  let hi = Math.round(QUALITY_CEILING * 100);
  let best: { blob: Blob; quality: number } | null = null;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const blob = await canvas.convertToBlob({ type, quality: mid / 100 });
    if (blob.size <= limit) {
      best = { blob, quality: mid / 100 };
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

export async function fitImageLocally(
  file: File,
  target: string,
  maxBytes: number,
  dims?: Dimensions
): Promise<LocalResult> {
  const bitmap = await createImageBitmap(file);
  try {
    // Resize first: budget spent on pixels about to be thrown away is wasted.
    const [baseW, baseH] = sizedTo(bitmap, dims);
    const alpha = hasAlpha(bitmap);
    let ext = target;
    if (target === "auto") {
      const sourceExt = extensionOf(file.name);
      ext = sourceExt === "jpeg" ? "jpg" : sourceExt;
      if (NO_QUALITY_DIAL.includes(ext)) {
        // Keep the format when it already fits. When it doesn't, a format
        // with no quality dial can only meet the budget by dropping pixels —
        // so move to one that can, and keep the picture whole.
        const asIs = await draw(bitmap, baseW, baseH, false)
          .convertToBlob({ type: "image/png" });
        ext = asIs.size <= maxBytes ? "png" : alpha ? "webp" : "jpg";
      }
    }
    const type = IMAGE_OUT[ext];
    if (!type) throw new Error(`no local encoder for .${ext}`);
    const opaque = type === "image/jpeg";
    const name = `${file.name.replace(/\.[^.]+$/, "")}.${ext}`;

    if (type !== "image/png") {
      const full = draw(bitmap, baseW, baseH, opaque);
      const best = await bestUnder(full, type, maxBytes);
      if (best && best.quality >= QUALITY_FLOOR) return { blob: best.blob, name };
    }

    // Out of quality: remove pixels, solving for the scale rather than
    // stepping blindly toward it.
    const probe = await draw(bitmap, baseW, baseH, opaque)
      .convertToBlob({ type, quality: QUALITY_CEILING });
    let scale = Math.min(1, Math.sqrt(maxBytes / probe.size) * 0.95);
    for (let attempt = 0; attempt < 8; attempt++) {
      const w = Math.max(1, Math.round(baseW * scale));
      const h = Math.max(1, Math.round(baseH * scale));
      const canvas = draw(bitmap, w, h, opaque);
      if (type === "image/png") {
        const blob = await canvas.convertToBlob({ type });
        if (blob.size <= maxBytes) return { blob, name };
      } else {
        const got = await bestUnder(canvas, type, maxBytes);
        if (got) return { blob: got.blob, name };
      }
      if (Math.min(w, h) <= 16) break;
      scale *= 0.85;
    }
    throw new Error("this file needs the engine");
  } finally {
    bitmap.close();
  }
}
