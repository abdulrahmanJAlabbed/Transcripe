// Subpath imports keep the bundle to the six faces we actually draw with,
// instead of every weight in each family.
import { useFonts } from "expo-font";
import { Inter_400Regular } from "@expo-google-fonts/inter/400Regular";
import { Inter_500Medium } from "@expo-google-fonts/inter/500Medium";
import { Inter_600SemiBold } from "@expo-google-fonts/inter/600SemiBold";
import { Inter_700Bold } from "@expo-google-fonts/inter/700Bold";
import { JetBrainsMono_400Regular } from "@expo-google-fonts/jetbrains-mono/400Regular";
import { JetBrainsMono_500Medium } from "@expo-google-fonts/jetbrains-mono/500Medium";
import * as Clipboard from "expo-clipboard";
import * as DocumentPicker from "expo-document-picker";
import type { File as FsFile } from "expo-file-system";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import * as Sharing from "expo-sharing";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View
} from "react-native";
import {
  SafeAreaProvider,
  useSafeAreaInsets
} from "react-native-safe-area-context";
import {
  API,
  cancelJob,
  convertFile,
  convertUrl,
  health,
  pruneCache,
  transcribeFile
} from "./src/api";
import {
  detectPlatform,
  extOf,
  firstUrl,
  formatBytes,
  kindOf,
  parseSize,
  SIZE_PRESETS,
  TARGETS,
  TEXT_TARGETS,
  URL_TARGETS,
  type Kind
} from "./src/formats";
import { f, Palette, radius, shadows, usePalette } from "./src/theme";
import { Body, Chip, Cta, Display, Label, loopSlide, Mono, Segmented, Tap, Track } from "./src/ui";

SplashScreen.preventAutoHideAsync().catch(() => {});

type Mode = "file" | "url";
type Phase = "idle" | "working" | "done";
type Picked = { uri: string; name: string; size?: number; mimeType?: string; ext: string };

/* Resolution choice only means something for video targets. */
const URL_AUDIO_ONLY = ["mp3", "m4a", "wav", "flac"];

export default function App() {
  return (
    <SafeAreaProvider>
      <Studio />
    </SafeAreaProvider>
  );
}

function Studio() {
  const insets = useSafeAreaInsets();
  const { c, isDark } = usePalette();
  const st = useMemo(() => makeStyles(c, isDark), [c, isDark]);
  const shadow = useMemo(() => shadows(isDark), [isDark]);
  const { width } = useWindowDimensions();
  const cardWidth = Math.min(width - 32, 520);

  const [fontsLoaded] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
    JetBrainsMono_400Regular,
    JetBrainsMono_500Medium
  });

  const [mode, setMode] = useState<Mode>("file");
  const [picked, setPicked] = useState<Picked | null>(null);
  const [url, setUrl] = useState("");
  const [target, setTarget] = useState("mp4");
  const [useCookies, setUseCookies] = useState(true);
  const [linkQuality, setLinkQuality] = useState<"best" | "compatible">("best");
  /* Images only: an upload limit to land under, as typed ("500KB"). */
  const [maxSize, setMaxSize] = useState("");
  /* Images only: longest edge in pixels, as typed. Blank = leave it alone. */
  const [longestEdge, setLongestEdge] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState<FsFile | null>(null);
  const [engineOn, setEngineOn] = useState<boolean | null>(null);
  const [engineLocked, setEngineLocked] = useState(false);
  const [canTranscribe, setCanTranscribe] = useState(true);
  const [canData, setCanData] = useState(true);

  const abortRef = useRef<AbortController | null>(null);
  const jobRef = useRef<string | null>(null);
  const slide = useRef(new Animated.Value(0)).current;

  /* Cancelling should free the laptop, not just stop this phone listening. */
  const cancelWork = () => {
    const job = jobRef.current;
    if (job) {
      jobRef.current = null;
      cancelJob(job);
    }
    abortRef.current?.abort();
  };

  const kind: Kind | null = picked ? kindOf(picked.ext) : null;
  const platform = detectPlatform(url);
  /* Only images have a size budget: it is the one job where what you want is
     a number of kilobytes rather than a different format. */
  const maxBytes =
    kind === "image" && maxSize.trim() ? parseSize(maxSize) : null;
  const edge =
    kind === "image" && longestEdge.trim() ? Number(longestEdge) : null;

  /* Arming a budget changes the question from "which format" to "how small",
     so let the engine choose until the user takes the choice back. */
  useEffect(() => {
    if (kind !== "image") {
      if (maxSize) setMaxSize("");
      if (longestEdge) setLongestEdge("");
      return;
    }
    if (maxBytes && target !== "auto") setTarget("auto");
    if (!maxBytes && target === "auto") setTarget(TARGETS.image.main[0]);
  }, [kind, maxBytes, target, maxSize, longestEdge]);

  const onLayoutRoot = useCallback(() => {
    if (fontsLoaded) SplashScreen.hideAsync().catch(() => {});
  }, [fontsLoaded]);

  /* Yesterday's results are already saved or forgotten — don't hoard them. */
  useEffect(() => {
    pruneCache();
  }, []);

  /* Engine heartbeat. */
  useEffect(() => {
    let alive = true;
    // Two misses before calling it offline: a phone on flaky Wi-Fi (or a
    // laptop mid-transcode) shouldn't be told the engine died.
    let misses = 0;
    const ping = async () => {
      const info = await health();
      if (!alive) return;
      if (info) {
        misses = 0;
        setEngineOn(true);
        setEngineLocked(!!info.auth_required && !info.authorized);
        // An engine without Whisper shouldn't be offered transcription.
        if (info.features) {
          setCanTranscribe(info.features.transcribe !== false);
          setCanData(info.features.data !== false);
        }
      } else {
        misses += 1;
        if (misses >= 2) setEngineOn(false);
      }
    };
    ping();
    const t = setInterval(ping, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  /* Elapsed ticker + sliding bar while the engine works. */
  useEffect(() => {
    if (phase !== "working") return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    const anim = loopSlide(slide);
    anim.start();
    return () => {
      clearInterval(t);
      anim.stop();
    };
  }, [phase, slide]);

  const reset = () => {
    setPhase("idle");
    setResult(null);
    setError("");
  };

  const acceptPick = (p: Picked) => {
    setPicked(p);
    const k = kindOf(p.ext);
    if (k !== "other") {
      const opts = TARGETS[k];
      const from = p.ext.replace(/^jpeg$/, "jpg");
      const choices = [...opts.main, ...(opts.audio ?? [])].filter(
        (fmt) => fmt !== from
      );
      // Default to something that actually changes the file.
      setTarget((t) => (choices.includes(t) ? t : choices[0] ?? opts.main[0]));
    }
    reset();
  };

  const pickFromLibrary = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      setError("Photo access is off — allow it in Settings, or use Browse files.");
      return;
    }
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images", "videos"],
      quality: 1
    });
    if (res.canceled || !res.assets?.length) return;
    const a = res.assets[0];
    const name = a.fileName || `media.${a.uri.split(".").pop() || "mp4"}`;
    acceptPick({
      uri: a.uri,
      name,
      size: a.fileSize,
      mimeType: a.mimeType,
      ext: extOf(name)
    });
  };

  const pickFromFiles = async () => {
    const res = await DocumentPicker.getDocumentAsync({
      type: "*/*",
      copyToCacheDirectory: true
    });
    if (res.canceled || !res.assets?.length) return;
    const a = res.assets[0];
    acceptPick({
      uri: a.uri,
      name: a.name,
      size: a.size,
      mimeType: a.mimeType,
      ext: extOf(a.name)
    });
  };

  /** `silent` is used by the auto-paste on mode switch: offering a link is a
   *  courtesy, so an empty clipboard shouldn't scold anyone. */
  const pasteLink = async (silent = false) => {
    const text = await Clipboard.getStringAsync();
    const found = firstUrl(text ?? "");
    if (found) {
      setUrl(found);
      setTarget((t) => (URL_TARGETS.includes(t) ? t : "mp4"));
      reset();
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(
        () => {}
      );
    } else if (!silent) {
      setError("No link on the clipboard yet — copy one first.");
    }
  };

  const switchMode = (m: string) => {
    const next = m as Mode;
    setMode(next);
    setError("");
    if (next === "url") {
      setTarget((t) => (URL_TARGETS.includes(t) ? t : "mp4"));
      if (!url) pasteLink(true).catch(() => {});
    } else if (kind && kind !== "other") {
      const opts = TARGETS[kind];
      setTarget((t) =>
        [...opts.main, ...(opts.audio ?? [])].includes(t) ? t : opts.main[0]
      );
    }
  };

  const run = async () => {
    Keyboard.dismiss();
    setError("");
    setPhase("working");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      let out: FsFile;
      if (mode === "url") {
        setStatus(`Fetching ${platform ?? "link"} → .${target}`);
        out = await convertUrl(
          {
            url: url.trim(),
            format: target,
            useBrowserCookies: useCookies,
            quality: linkQuality
          },
          controller.signal
        );
      } else if (
        TEXT_TARGETS.includes(target) &&
        (kind === "audio" || kind === "video")
      ) {
        setStatus(`${picked!.name} → .${target}`);
        out = await transcribeFile(
          {
            uri: picked!.uri,
            name: picked!.name,
            mimeType: picked!.mimeType,
            format: target
          },
          setStatus,
          (job) => {
            jobRef.current = job;
          },
          controller.signal
        );
        jobRef.current = null;
      } else {
        setStatus(`${picked!.name} → .${target}`);
        out = await convertFile(
          {
            uri: picked!.uri,
            name: picked!.name,
            mimeType: picked!.mimeType,
            format: target,
            maxSize: maxBytes ?? undefined,
            // The phone can't cheaply read the picture's orientation before
            // upload, so the longest edge goes as a width cap and the engine
            // scales the other side to match.
            width: edge
          },
          (fraction) => {
            const pct = Math.round(fraction * 100);
            setStatus(`${picked!.name} → .${target}${pct ? ` · ${pct}%` : ""}`);
          },
          (job) => {
            jobRef.current = job;
          },
          controller.signal
        );
        jobRef.current = null;
      }
      setResult(out);
      setPhase("done");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(
        () => {}
      );
    } catch (err: unknown) {
      const e = err as Error;
      if (e?.name === "AbortError") {
        setPhase("idle");
        return;
      }
      setError(
        e?.message?.includes("Network request failed")
          ? `Can't reach the engine at ${API}. Same Wi-Fi? Started with TRANSCRIPE_HOST=0.0.0.0?`
          : e?.message || "Conversion failed."
      );
      setPhase("idle");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(
        () => {}
      );
    } finally {
      abortRef.current = null;
    }
  };

  const saveResult = async () => {
    if (!result) return;
    if (!(await Sharing.isAvailableAsync())) {
      setError("Sharing isn't available on this device.");
      return;
    }
    await Sharing.shareAsync(result.uri, {
      dialogTitle: "Save or share",
      mimeType: "application/octet-stream"
    });
  };

  const startOver = () => {
    setPicked(null);
    setUrl("");
    reset();
  };

  const canRun =
    phase !== "working" &&
    (mode === "url"
      ? url.trim().length > 0
      : !!picked && kind !== "other" && !!target);

  const targets =
    mode === "url"
      ? URL_TARGETS
      : kind && kind !== "other"
      ? (kind === "data" && !canData
          ? []
          : [...TARGETS[kind].main, ...(TARGETS[kind].audio ?? [])]
        ).filter(
          // Converting a file to what it already is does nothing — unless the
          // point is the size, in which case it does.
          (t) => maxBytes !== null || t !== picked?.ext.replace(/^jpeg$/, "jpg")
        )
      : [];
  const textTargets =
    canTranscribe && mode === "file" && kind && kind !== "other"
      ? TARGETS[kind].text ?? []
      : [];
  // Converting a file to the format it already is does nothing useful.
  const sourceExt = picked ? picked.ext.replace(/^jpeg$/, "jpg") : "";

  if (!fontsLoaded) {
    return (
      <View style={[st.boot, { backgroundColor: c.paper }]}>
        <ActivityIndicator color={c.clay} />
      </View>
    );
  }

  return (
    <View style={st.root} onLayout={onLayoutRoot}>
      <StatusBar style={isDark ? "light" : "dark"} />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerStyle={[
            st.scroll,
            { paddingTop: insets.top + 14, paddingBottom: insets.bottom + 36 }
          ]}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* Header */}
          <View style={st.head}>
            <Text style={st.wordmark}>
              Transcripe<Text style={{ color: c.clay }}>.</Text>
            </Text>
            <View style={st.statusPill}>
              <View
                style={[
                  st.dot,
                  {
                    backgroundColor:
                      engineOn === null ? c.ink3 : engineOn ? c.ok : c.err
                  }
                ]}
              />
              <Mono style={{ fontSize: 10.5 }}>
                {engineOn === null
                  ? "checking"
                  : !engineOn
                  ? "engine off"
                  : engineLocked
                  ? "locked"
                  : "engine on"}
              </Mono>
            </View>
          </View>

          {/* Hero */}
          <View style={st.hero}>
            <Label>local · private · yours</Label>
            <Display style={{ marginTop: 12 }}>
              Every file,{" "}
              <Text style={{ fontFamily: f.display, color: c.clay }}>
                quietly
              </Text>{" "}
              transformed.
            </Display>
            <Body style={{ marginTop: 12 }}>
              Pick a video or paste a link. Your laptop does the work — nothing
              touches a cloud.
            </Body>
          </View>

          {/* Card */}
          <View style={[st.card, { width: cardWidth }]}>
            <Segmented
              width={cardWidth - 36}
              value={mode}
              onChange={switchMode}
              options={[
                { key: "file", label: "From my phone" },
                { key: "url", label: "From a link" }
              ]}
            />

            {mode === "file" ? (
              picked ? (
                <View style={st.pickedRow}>
                  <View style={st.extBadge}>
                    <Mono style={{ fontSize: 10, color: c.ink2 }}>
                      {(picked.ext || "file").toUpperCase()}
                    </Mono>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={st.pickedName} numberOfLines={1}>
                      {picked.name}
                    </Text>
                    {!!picked.size && (
                      <Mono style={{ fontSize: 11 }}>{formatBytes(picked.size)}</Mono>
                    )}
                  </View>
                  <Tap onPress={startOver} style={st.clearBtn}>
                    <Text style={{ color: c.ink3, fontSize: 18, lineHeight: 20 }}>
                      ×
                    </Text>
                  </Tap>
                </View>
              ) : (
                <View style={{ gap: 10 }}>
                  <Tap onPress={pickFromLibrary} style={st.pickPrimary}>
                    <View style={st.plusCircle}>
                      <Text style={st.plusText}>+</Text>
                    </View>
                    <Text style={st.pickTitle}>Photos & videos</Text>
                    <Mono style={{ fontSize: 11, marginTop: 2 }}>
                      straight from the camera roll
                    </Mono>
                  </Tap>
                  <Tap onPress={pickFromFiles} style={st.pickGhost}>
                    <Text style={st.pickGhostText}>Browse files instead</Text>
                  </Tap>
                </View>
              )
            ) : (
              <View style={{ gap: 12 }}>
                <View style={st.urlWrap}>
                  <TextInput
                    style={st.urlInput}
                    value={url}
                    onChangeText={(t) => {
                      setUrl(t);
                      if (error) setError("");
                      if (phase === "done") reset();
                    }}
                    placeholder="Paste a YouTube, TikTok, Instagram link…"
                    placeholderTextColor={c.ink3}
                    autoCapitalize="none"
                    autoCorrect={false}
                    keyboardType="url"
                    returnKeyType="go"
                    onSubmitEditing={() => canRun && run()}
                  />
                  <Tap onPress={pasteLink} style={st.pasteBtn} haptic="light">
                    <Text style={st.pasteText}>Paste</Text>
                  </Tap>
                </View>
                {platform ? (
                  <View style={st.detect}>
                    <View style={[st.dot, { backgroundColor: c.clay }]} />
                    <Mono style={{ color: c.ink2 }}>{platform} detected</Mono>
                  </View>
                ) : (
                  <Body style={{ fontSize: 13, color: c.ink3 }}>
                    1,000+ sites — reels without watermarks, shorts, clips, tracks.
                  </Body>
                )}
                {!URL_AUDIO_ONLY.includes(target) && (
                  <View style={{ gap: 9 }}>
                    <Label>quality</Label>
                    <View style={st.chips}>
                      <Chip
                        label="best available"
                        active={linkQuality === "best"}
                        onPress={() => setLinkQuality("best")}
                      />
                      <Chip
                        label="most compatible"
                        active={linkQuality === "compatible"}
                        onPress={() => setLinkQuality("compatible")}
                      />
                    </View>
                  </View>
                )}

                <Tap
                  onPress={() => setUseCookies((v) => !v)}
                  style={st.checkRow}
                  haptic="light"
                >
                  <View style={[st.checkbox, useCookies && st.checkboxOn]}>
                    {useCookies && <Text style={st.checkMark}>✓</Text>}
                  </View>
                  <Body style={{ flex: 1, fontSize: 13 }}>
                    Use the laptop's browser cookies for private or age-gated links
                  </Body>
                </Tap>
              </View>
            )}

            {/* A size budget — images are the one kind where people arrive
                with a number in mind rather than a format. */}
            {mode === "file" && kind === "image" && (
              <View style={{ gap: 9 }}>
                <Label>maximum size</Label>
                <View style={st.chips}>
                  <Chip
                    label="no limit"
                    active={!maxSize}
                    onPress={() => setMaxSize("")}
                  />
                  {SIZE_PRESETS.map((preset) => (
                    <Chip
                      key={preset}
                      label={preset.replace(/(KB|MB)/, " $1")}
                      active={maxSize === preset}
                      onPress={() => setMaxSize(preset)}
                    />
                  ))}
                </View>
                {maxBytes !== null && (
                  <Body style={{ fontSize: 12, color: c.ink3 }}>
                    Quality goes before pixels — the picture keeps its size on
                    screen unless the budget leaves no other way.
                  </Body>
                )}
              </View>
            )}

            {mode === "file" && kind === "image" && (
              <View style={{ gap: 9 }}>
                <Label>width</Label>
                <View style={st.chips}>
                  <Chip
                    label="original"
                    active={!longestEdge}
                    onPress={() => setLongestEdge("")}
                  />
                  {["1920", "1280", "800"].map((px) => (
                    <Chip
                      key={px}
                      label={`${px} px`}
                      active={longestEdge === px}
                      onPress={() => setLongestEdge(px)}
                    />
                  ))}
                </View>
                {edge !== null && (
                  <Body style={{ fontSize: 12, color: c.ink3 }}>
                    The height follows, so the picture keeps its shape.
                  </Body>
                )}
              </View>
            )}

            {/* Targets */}
            {targets.length > 0 && (mode === "url" ? !!url.trim() : !!picked) && (
              <View style={{ gap: 9 }}>
                <Label>{mode === "url" ? "save as" : "convert to"}</Label>
                <View style={st.chips}>
                  {maxBytes !== null && (
                    <Chip
                      label="best fit"
                      active={target === "auto"}
                      onPress={() => setTarget("auto")}
                    />
                  )}
                  {targets.map((t) => (
                    <Chip
                      key={t}
                      label={`.${t}`}
                      active={target === t}
                      onPress={() => setTarget(t)}
                    />
                  ))}
                </View>
              </View>
            )}

            {textTargets.length > 0 && !!picked && (
              <View style={{ gap: 9 }}>
                <Label>transcribe — whisper on your laptop</Label>
                <View style={st.chips}>
                  {textTargets.map((t) => (
                    <Chip
                      key={t}
                      label={`.${t}`}
                      active={target === t}
                      onPress={() => setTarget(t)}
                    />
                  ))}
                </View>
              </View>
            )}

            {mode === "file" && picked && kind === "other" && (
              <View style={st.note}>
                <Body style={{ fontSize: 13, color: c.ink2 }}>
                  .{picked.ext} needs the desktop CLI —{" "}
                  <Text style={{ fontFamily: f.mono, fontSize: 12 }}>
                    transcripe {picked.ext} …
                  </Text>{" "}
                  on your laptop handles it.
                </Body>
              </View>
            )}

            {engineOn === false && (
              <View style={st.note}>
                <Body style={{ fontSize: 13, color: c.ink2 }}>
                  Engine offline. On your laptop:{" "}
                  <Text style={{ fontFamily: f.mono, fontSize: 12 }}>
                    transcripe studio --lan
                  </Text>
                </Body>
              </View>
            )}

            {engineOn && engineLocked && (
              <View style={st.note}>
                <Body style={{ fontSize: 13, color: c.ink2 }}>
                  The engine is reachable but locked. Copy the token it printed
                  on startup into{" "}
                  <Text style={{ fontFamily: f.mono, fontSize: 12 }}>
                    EXPO_PUBLIC_API_TOKEN
                  </Text>{" "}
                  in mobile/.env, then restart Expo.
                </Body>
              </View>
            )}

            {!!error && (
              <Tap onPress={() => setError("")} style={st.errBox} haptic="none">
                <Body style={{ fontSize: 13, color: c.err }}>{error}</Body>
              </Tap>
            )}

            {/* Action zone */}
            {phase === "working" ? (
              <View style={{ gap: 11 }}>
                <View style={st.workRow}>
                  <Text style={st.workLabel} numberOfLines={1}>
                    {status}
                  </Text>
                  <Mono>
                    {Math.floor(elapsed / 60)}:
                    {String(elapsed % 60).padStart(2, "0")}
                  </Mono>
                </View>
                <Track animate={slide} />
                <Tap
                  onPress={cancelWork}
                  style={{ alignSelf: "center", paddingVertical: 6 }}
                >
                  <Body style={{ fontSize: 13, color: c.ink3 }}>Cancel</Body>
                </Tap>
              </View>
            ) : phase === "done" && result ? (
              <View style={{ gap: 12 }}>
                <View style={st.doneRow}>
                  <View style={st.doneCheck}>
                    <Text style={{ color: c.ok, fontSize: 16 }}>✓</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={st.doneName} numberOfLines={1}>
                      {result.name}
                    </Text>
                    <Mono style={{ fontSize: 11 }}>
                      {formatBytes(result.size) || "ready"} · on this phone
                    </Mono>
                  </View>
                </View>
                <Cta label="Save or share" onPress={saveResult} />
                <Tap
                  onPress={startOver}
                  style={{ alignSelf: "center", paddingVertical: 6 }}
                >
                  <Body style={{ fontSize: 13, color: c.ink3 }}>
                    Convert another
                  </Body>
                </Tap>
              </View>
            ) : (
              <Cta
                label={
                  mode === "url"
                    ? `Fetch & convert to .${target}`
                    : kind === "other"
                    ? "Not supported on mobile"
                    : TEXT_TARGETS.includes(target) &&
                      (kind === "audio" || kind === "video")
                    ? `Transcribe to .${target}`
                    : `Convert to .${target}`
                }
                onPress={run}
                disabled={!canRun}
              />
            )}
          </View>

          <Mono style={{ marginTop: 20, fontSize: 10.5, textAlign: "center" }}>
            processed on your machine · deleted right after
          </Mono>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const makeStyles = (c: Palette, isDark: boolean) => {
  const shadow = shadows(isDark);
  return StyleSheet.create({
  root: { flex: 1, backgroundColor: c.paper },
  boot: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { alignItems: "center", paddingHorizontal: 16 },

  head: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 26
  },
  wordmark: {
    fontFamily: f.display,
    fontSize: 20,
    letterSpacing: -0.6,
    color: c.ink
  },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6 },
  dot: { width: 7, height: 7, borderRadius: 4 },

  hero: { width: "100%", marginBottom: 26 },

  card: {
    backgroundColor: c.card,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: c.line,
    padding: 18,
    gap: 16,
    ...shadow.card
  },

  pickPrimary: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 30,
    borderRadius: radius.field,
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: c.lineStrong
  },
  plusCircle: {
    width: 44,
    height: 44,
    borderRadius: 22,
    borderWidth: 1.5,
    borderColor: c.lineStrong,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12
  },
  plusText: { color: c.ink2, fontSize: 22, lineHeight: 25 },
  pickTitle: { fontFamily: f.bodySemi, fontSize: 15.5, color: c.ink },
  pickGhost: {
    paddingVertical: 12,
    borderRadius: radius.inner,
    backgroundColor: c.well,
    alignItems: "center"
  },
  pickGhostText: { fontFamily: f.bodyMedium, fontSize: 14, color: c.ink2 },

  pickedRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 11,
    padding: 12,
    borderRadius: radius.inner,
    borderWidth: 1,
    borderColor: c.line
  },
  extBadge: {
    paddingHorizontal: 7,
    paddingVertical: 4,
    borderRadius: 6,
    backgroundColor: c.well
  },
  pickedName: { fontFamily: f.bodyMedium, fontSize: 14.5, color: c.ink },
  clearBtn: {
    width: 30,
    height: 30,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center"
  },

  urlWrap: { flexDirection: "row", alignItems: "center" },
  urlInput: {
    flex: 1,
    height: 50,
    paddingHorizontal: 15,
    paddingRight: 74,
    borderRadius: radius.field,
    borderWidth: 1,
    borderColor: c.lineStrong,
    backgroundColor: c.card,
    fontFamily: f.body,
    fontSize: 14.5,
    color: c.ink
  },
  pasteBtn: {
    position: "absolute",
    right: 7,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 9,
    backgroundColor: c.well
  },
  pasteText: { fontFamily: f.bodySemi, fontSize: 13, color: c.ink2 },
  detect: { flexDirection: "row", alignItems: "center", gap: 8 },

  checkRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 6,
    borderWidth: 1.5,
    borderColor: c.lineStrong,
    alignItems: "center",
    justifyContent: "center"
  },
  checkboxOn: { backgroundColor: c.clay, borderColor: c.clay },
  checkMark: { color: "#fff8f2", fontSize: 12, lineHeight: 14 },

  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },

  note: {
    padding: 13,
    borderRadius: radius.inner,
    backgroundColor: c.well
  },
  errBox: {
    padding: 13,
    borderRadius: radius.inner,
    backgroundColor: c.errSoft,
    borderWidth: 1,
    borderColor: "rgba(179, 55, 42, 0.22)"
  },

  workRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12
  },
  workLabel: { flex: 1, fontFamily: f.bodyMedium, fontSize: 14, color: c.ink },

  doneRow: { flexDirection: "row", alignItems: "center", gap: 11 },
  doneCheck: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: c.okSoft,
    alignItems: "center",
    justifyContent: "center"
  },
  doneName: { fontFamily: f.bodySemi, fontSize: 14.5, color: c.ink }
});
};
