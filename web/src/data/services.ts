import {
  Archive,
  BadgeCheck,
  Captions,
  Code2,
  FileArchive,
  FileImage,
  FileJson,
  FileText,
  Film,
  ImageDown,
  Layers3,
  Mic2,
  ScanText,
  Scissors,
  SearchCheck,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Table2,
  TextCursorInput,
  Wand2
} from "lucide-react";

export type ServiceCategory =
  | "All"
  | "PDF"
  | "Media"
  | "Images"
  | "Documents"
  | "Data"
  | "Archives"
  | "3D"
  | "Text";

export type Service = {
  id: string;
  category: Exclude<ServiceCategory, "All">;
  title: string;
  summary: string;
  inputs: string[];
  outputs: string[];
  command: string;
  api: string;
  engine: string;
  speed: string;
  privacy: "browser-ready" | "ephemeral-server" | "local-cli";
  icon: typeof FileText;
  priority?: boolean;
};

export const serviceCategories: ServiceCategory[] = [
  "All",
  "PDF",
  "Media",
  "Images",
  "Documents",
  "Data",
  "Archives",
  "3D",
  "Text"
];

export const services: Service[] = [
  {
    id: "transcribe",
    category: "Media",
    title: "Whisper AI Transcription",
    summary: "Create TXT or SRT subtitles from lectures, meetings, podcasts, and recordings.",
    inputs: ["mp4", "mkv", "mov", "webm", "avi", "3gp", "mp3", "wav", "m4a", "flac", "aac", "ogg", "opus", "wma"],
    // Whisper writes txt/srt; .vtt comes from the subtitle workbench afterwards.
    outputs: ["txt", "srt"],
    command: "transcripe media transcribe meeting.mp4 --srt",
    api: "POST /api/transcribe",
    engine: "faster-whisper + FFmpeg",
    speed: "GPU when available, CPU fallback",
    privacy: "ephemeral-server",
    icon: Mic2,
    priority: true
  },
  {
    id: "social-downloader",
    category: "Media",
    title: "Instagram, TikTok & YouTube Downloader",
    summary: "Download HD Instagram Reels, watermark-free TikToks, YouTube shorts, and Twitter clips.",
    inputs: ["url", "link", "instagram", "tiktok", "youtube", "twitter"],
    outputs: ["mp4", "mp3", "m4a", "wav"],
    command: "transcripe download https://instagram.com/reel/... --to mp4",
    api: "POST /api/jobs/media/download",
    engine: "yt-dlp + gallery-dl + FFmpeg",
    speed: "Direct stream extraction",
    privacy: "ephemeral-server",
    icon: Film,
    priority: true
  },
  {
    id: "pdf-edit",
    category: "PDF",
    title: "Editable PDF Workspace",
    summary: "Turn text or scanned PDFs into editable HTML/Word while preserving page layout.",
    inputs: ["pdf"],
    outputs: ["html", "docx", "pdf", "txt"],
    command: "transcripe pdf edit contract.pdf",
    api: "POST /api/jobs/pdf/editable",
    engine: "PyMuPDF, OCR overlays, Chromium print",
    speed: "Page-streamed progress",
    privacy: "ephemeral-server",
    icon: TextCursorInput,
    priority: true
  },
  {
    id: "pdf-searchable",
    category: "PDF",
    title: "Searchable Scanned PDFs",
    summary: "Add an invisible OCR text layer so scanned document images become searchable.",
    inputs: ["pdf"],
    outputs: ["pdf"],
    command: "transcripe pdf searchable scan.pdf --lang en,tr",
    api: "POST /api/jobs/pdf/searchable",
    engine: "OCRmyPDF + Tesseract",
    speed: "Page-by-page OCR",
    privacy: "ephemeral-server",
    icon: SearchCheck,
    priority: true
  },
  {
    id: "pdf-split-merge",
    category: "PDF",
    title: "Strip & Extract PDF Pages",
    summary: "Strip PDF pages to separate PDFs or extract pages as individual PNG/JPG images.",
    inputs: ["pdf"],
    outputs: ["pdf", "png", "jpg"],
    command: "transcripe pdf split report.pdf --pages 1-5",
    api: "POST /api/jobs/pdf/pages",
    engine: "pypdf + Poppler",
    speed: "Fast stream operations",
    privacy: "ephemeral-server",
    icon: Scissors,
    priority: true
  },
  {
    id: "pdf-combine",
    category: "PDF",
    title: "Combine & Merge into 1 PDF",
    summary: "Merge multiple documents, images, or PDF files into a single formatted PDF document.",
    inputs: ["pdf", "png", "jpg", "jpeg", "webp", "docx", "txt", "md"],
    outputs: ["pdf"],
    command: "transcripe pdf merge doc1.pdf doc2.png --to unified.pdf",
    api: "POST /api/jobs/pdf/merge",
    engine: "pypdf + Pillow + ReportLab",
    speed: "Streaming merge pipeline",
    privacy: "ephemeral-server",
    icon: Layers3,
    priority: true
  },
  {
    id: "image-ocr",
    category: "Images",
    title: "Multilingual Image OCR",
    summary: "Extract readable text from screenshots, forms, receipts, and scans.",
    inputs: ["png", "jpg", "jpeg", "webp", "avif", "tiff", "bmp", "heic"],
    outputs: ["txt", "pdf", "docx"],
    command: "transcripe scan.png --to txt",
    api: "POST /api/jobs/image/ocr",
    engine: "RapidOCR with EasyOCR fallback",
    speed: "Lazy-loaded OCR engines",
    privacy: "ephemeral-server",
    icon: ScanText,
    priority: true
  },
  {
    id: "image-resize-compress",
    category: "Images",
    title: "Resize, Vectorize & Fit Size Rules",
    summary: "Hit an exact upload limit — 500 KB, 2 MB — spending quality before pixels, so the picture keeps its size on screen.",
    inputs: ["png", "jpg", "jpeg", "webp", "avif", "gif", "svg", "bmp", "tiff", "ico"],
    outputs: ["png", "jpg", "webp", "avif", "svg", "pdf"],
    command: "transcripe image fit-size photo.png --max 500KB",
    api: "POST /api/jobs/image/optimize",
    engine: "Pillow, HEIF, CairoSVG, Potrace",
    speed: "Binary search, encoded in memory",
    privacy: "browser-ready",
    icon: SlidersHorizontal,
    priority: true
  },
  {
    id: "document-convert",
    category: "Documents",
    title: "Office & Document Converter",
    summary: "Convert Word, Excel, PowerPoint, EPUB, RTF, HTML, and Markdown to PDF or text.",
    inputs: ["doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "ods", "odp", "epub", "mobi", "azw3", "rtf", "md", "html", "tex"],
    outputs: ["pdf", "docx", "html", "md", "txt"],
    command: "transcripe slides.pptx --to pdf",
    api: "POST /api/jobs/documents/convert",
    engine: "LibreOffice, MS Office, Pandoc",
    speed: "Backend chosen by fidelity",
    privacy: "ephemeral-server",
    icon: FileText,
    priority: true
  },
  {
    id: "media-convert",
    category: "Media",
    title: "Media Converter & Audio Extractor",
    summary: "Convert audio/video formats, extract sound tracks, trim clips, and build animated GIFs.",
    inputs: ["mp4", "mkv", "avi", "mov", "webm", "3gp", "mp3", "wav", "m4a", "flac", "aac", "ogg", "wma"],
    outputs: ["mp3", "mp4", "wav", "flac", "aac", "gif", "webm"],
    command: "transcripe media gif clip.mp4 --fps 12 --width 640",
    api: "POST /api/jobs/media/convert",
    engine: "FFmpeg",
    speed: "Stream copy when possible",
    privacy: "ephemeral-server",
    icon: Film
  },
  {
    id: "subtitles",
    category: "Media",
    title: "Subtitle Format Workbench",
    summary: "Convert SRT, VTT, ASS, SSA, strip timing codes, or burn captions into video files.",
    inputs: ["srt", "vtt", "ass", "ssa"],
    outputs: ["srt", "vtt", "ass", "txt"],
    command: "transcripe convert captions.srt --to vtt",
    api: "POST /api/jobs/subtitles/convert",
    engine: "Pure Python + FFmpeg burn-in",
    speed: "Instant text transforms",
    privacy: "browser-ready",
    icon: Captions
  },
  {
    id: "data-transform",
    category: "Data",
    title: "Data Table & Spreadsheet Converter",
    summary: "Convert between CSV, JSON, YAML, TOML, Excel, Parquet, TSV, and XML data files.",
    inputs: ["csv", "json", "yaml", "yml", "toml", "xlsx", "xls", "parquet", "tsv", "xml", "ndjson"],
    outputs: ["csv", "json", "xlsx", "parquet", "yaml", "xml"],
    command: "transcripe convert data.csv --to parquet",
    api: "POST /api/jobs/data/convert",
    engine: "pandas, PyArrow, OpenPyXL",
    speed: "Chunk-friendly stream processing",
    privacy: "browser-ready",
    icon: Table2,
    priority: true
  },
  {
    id: "json-cleanup",
    category: "Data",
    title: "Pretty Print & Minify Code Data",
    summary: "Format JSON, YAML, and XML files for reading or minify them for shipping.",
    inputs: ["json", "yaml", "yml", "xml", "toml"],
    outputs: ["json", "yaml", "xml"],
    command: "transcripe data pretty api_response.json",
    api: "POST /api/jobs/data/json",
    engine: "Pure Python parser",
    speed: "Instant execution",
    privacy: "browser-ready",
    icon: FileJson
  },
  {
    id: "archives",
    category: "Archives",
    title: "Archive Unpacker & Repacker",
    summary: "Extract, inspect, or compress ZIP, TAR, GZ, 7Z, and RAR archives safely.",
    inputs: ["zip", "tar", "gz", "tgz", "7z", "rar", "bz2"],
    outputs: ["zip", "tar.gz", "7z"],
    command: "transcripe archive extract backup.rar",
    api: "POST /api/jobs/archive/extract",
    engine: "stdlib, py7zr, rarfile, unar",
    speed: "Safe streaming extraction",
    privacy: "ephemeral-server",
    icon: FileArchive
  },
  {
    id: "models",
    category: "3D",
    title: "Web-Ready 3D GLB Converter",
    summary: "Convert FBX, OBJ, 3DS, DAE, STL, PLY, and glTF into web-optimized 3D GLB models.",
    inputs: ["fbx", "obj", "3ds", "dae", "stl", "ply", "glb", "gltf", "usdz"],
    outputs: ["glb", "gltf", "obj", "stl", "ply"],
    command: "transcripe model convert car.fbx --web",
    api: "POST /api/jobs/model/convert",
    engine: "assimp + glTF-Transform + Draco",
    speed: "90-97% smaller GLB targets",
    privacy: "ephemeral-server",
    icon: Layers3,
    priority: true
  },
  {
    id: "encoding",
    category: "Text",
    title: "Fix Text Encoding & Garbled Chars",
    summary: "Detect non-UTF-8 character encodings, repair corrupted text, and export clean UTF-8.",
    inputs: ["txt", "csv", "srt", "md", "json", "html"],
    outputs: ["utf-8", "txt"],
    command: "transcripe fix-encoding weird_chars.txt",
    api: "POST /api/jobs/text/encoding",
    engine: "charset-normalizer + heuristics",
    speed: "Instant text scan",
    privacy: "browser-ready",
    icon: BadgeCheck
  }
];

export const formatCategoryMap: Record<string, ServiceCategory> = {
  pdf: "PDF",
  mp4: "Media",
  mkv: "Media",
  avi: "Media",
  mov: "Media",
  webm: "Media",
  "3gp": "Media",
  mp3: "Media",
  wav: "Media",
  m4a: "Media",
  flac: "Media",
  aac: "Media",
  ogg: "Media",
  opus: "Media",
  wma: "Media",
  srt: "Media",
  vtt: "Media",
  ass: "Media",
  ssa: "Media",
  png: "Images",
  jpg: "Images",
  jpeg: "Images",
  webp: "Images",
  avif: "Images",
  heic: "Images",
  gif: "Images",
  svg: "Images",
  bmp: "Images",
  tiff: "Images",
  ico: "Images",
  docx: "Documents",
  doc: "Documents",
  pptx: "Documents",
  ppt: "Documents",
  xlsx: "Documents",
  xls: "Documents",
  odt: "Documents",
  ods: "Documents",
  odp: "Documents",
  epub: "Documents",
  mobi: "Documents",
  azw3: "Documents",
  rtf: "Documents",
  md: "Documents",
  html: "Documents",
  tex: "Documents",
  csv: "Data",
  json: "Data",
  yaml: "Data",
  yml: "Data",
  toml: "Data",
  parquet: "Data",
  tsv: "Data",
  xml: "Data",
  ndjson: "Data",
  zip: "Archives",
  tar: "Archives",
  gz: "Archives",
  tgz: "Archives",
  "7z": "Archives",
  rar: "Archives",
  bz2: "Archives",
  fbx: "3D",
  obj: "3D",
  "3ds": "3D",
  dae: "3D",
  stl: "3D",
  ply: "3D",
  glb: "3D",
  gltf: "3D",
  usdz: "3D",
  txt: "Text"
};

export const proofPoints = [
  { value: "14", label: "tool engines", icon: Sparkles },
  { value: "60+", label: "file formats", icon: FileImage },
  { value: "0", label: "cloud uploads required", icon: ShieldCheck },
  { value: "CLI + Web", label: "identical local core", icon: Code2 },
  { value: "100%", label: "private processing", icon: ImageDown }
];
