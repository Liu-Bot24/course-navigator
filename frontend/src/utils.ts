export function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const sec = total % 60;
  const minutesTotal = Math.floor(total / 60);
  const min = minutesTotal % 60;
  const hours = Math.floor(minutesTotal / 60);
  if (hours > 0) {
    return `${pad(hours)}:${pad(min)}:${pad(sec)}`;
  }
  return `${pad(min)}:${pad(sec)}`;
}

export function getYouTubeVideoId(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.hostname.includes("youtube.com")) {
      return parsed.searchParams.get("v");
    }
    if (parsed.hostname === "youtu.be") {
      return parsed.pathname.split("/").filter(Boolean)[0] ?? null;
    }
  } catch {
    return null;
  }
  return null;
}

const TRACKING_QUERY_PARAMS = new Set([
  "fbclid",
  "gclid",
  "share_from",
  "share_medium",
  "share_plat",
  "share_session_id",
  "share_source",
  "share_tag",
  "si",
  "spm_id_from",
  "timestamp",
  "unique_k",
  "vd_source",
]);

export function canonicalSourceKey(sourceUrl: string): string {
  const youtubeId = getYouTubeVideoId(sourceUrl);
  if (youtubeId) return `youtube:${youtubeId}`;
  try {
    const parsed = new URL(sourceUrl);
    parsed.hash = "";
    // The query can select a different video (such as ?p=2 for a multi-part
    // Bilibili upload); only sharing and tracking parameters are dropped.
    for (const key of [...parsed.searchParams.keys()]) {
      if (TRACKING_QUERY_PARAMS.has(key.toLowerCase()) || key.toLowerCase().startsWith("utm_")) {
        parsed.searchParams.delete(key);
      }
    }
    parsed.searchParams.sort();
    return parsed.toString().replace(/\/(?=$|\?)/, "");
  } catch {
    return sourceUrl.trim();
  }
}

export function getBilibiliVideoId(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (!parsed.hostname.includes("bilibili.com")) {
      return null;
    }
    const match = parsed.pathname.match(/\/video\/(BV[a-zA-Z0-9]+)/);
    return match?.[1] ?? null;
  } catch {
    return null;
  }
}

export function buildWebVttTrack(segments: Array<{ start: number; end: number; text: string }>): string {
  const cues = segments
    .map((segment, index) => {
      const text = segment.text.replace(/\s+/g, " ").trim();
      if (!text) return null;
      const start = Math.max(0, segment.start);
      const end = Math.max(start + 0.8, segment.end);
      return `${index + 1}\n${formatVttTime(start)} --> ${formatVttTime(end)}\n${text}`;
    })
    .filter(Boolean);
  return `WEBVTT\n\n${cues.join("\n\n")}\n`;
}

function pad(value: number): string {
  return value.toString().padStart(2, "0");
}

function formatVttTime(seconds: number): string {
  const totalMs = Math.max(0, Math.floor(seconds * 1000));
  const ms = totalMs % 1000;
  const totalSeconds = Math.floor(totalMs / 1000);
  const sec = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const min = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  return `${pad(hours)}:${pad(min)}:${pad(sec)}.${ms.toString().padStart(3, "0")}`;
}
