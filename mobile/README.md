# Transcripe — phone app

The studio, on your phone. Photos are resized and re-encoded **on the device
itself**, so they never leave it. Everything else — video, audio, subtitles,
tabular data, links — goes to the Transcripe engine and comes back.

Built with Expo SDK 54 — runs in **Expo Go**, no Xcode or Android Studio needed.

---

## Run it

```bash
npm install     # first time only
npx expo start
```

Scan the QR code with **Expo Go** (Android) or the **Camera app** (iOS).

That is the whole setup. The app talks to the hosted engine at
**alabed.site** by default, so there is nothing to configure, no address to
find, and no laptop that has to be awake and on the same Wi-Fi.

### Pointing it at your own engine (optional)

Only useful while developing. Copy `.env.example` to `.env` and set
`EXPO_PUBLIC_API_URL` to a studio started with `transcripe studio --lan`,
which binds `0.0.0.0` and prints the token to paste alongside it.

---

## Reading the app

**From my phone** picks a photo or video from the camera roll, or any file via
*Browse files instead*.

Images are handled on the phone: change the format, set exact dimensions, or
give a maximum file size and it searches for the best quality that fits.
Nothing is uploaded for these, and the engine's upload ceiling doesn't apply —
the app says as much when a job is staying put.

Everything else goes to the engine, including **transcription**: choose `.srt`
or `.txt` and Whisper runs there while the app polls, so a long recording
can't time out. Formats the engine can't take (PDF, DOCX, archives, 3D models)
belong to the desktop CLI, and the app says so instead of pretending.

**From a link** takes a YouTube / TikTok / Instagram / X / Spotify URL and
fetches it as video or audio. Switching to that tab offers whatever link is on
your clipboard.

Every finished file says where it was made — *on this phone* or *on the
engine* — and opens the native share sheet, so you can save to Files/Photos or
send it onward.

There is no engine status light. Whether the engine is reachable matters at
the moment something is being converted, and the attempt says so then.

---

## Notes

- Files are streamed to disk as they download, so a large video never has to
  fit in the app's memory.
- The engine hands back a one-shot download link that expires after 15 minutes
  and dies on first use.
- The hosted engine caps uploads at 100 MB and has no Whisper, so it doesn't
  offer transcription. On-device image work is bound by neither.
- `npm run web` opens the same app in a browser — handy for a quick look, but
  file picking and downloads behave differently there than on a real phone.
