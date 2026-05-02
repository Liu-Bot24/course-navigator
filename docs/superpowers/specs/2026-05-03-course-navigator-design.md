# Course Navigator Design

## Product

Course Navigator is a local-first video course study workspace. It turns video lessons into scannable, collapsible, timestamp-linked learning material so a working learner can quickly decide what to watch, what to skip, and where to return later.

The first version is for personal local use. It does not depend on Hermes or OpenClaw, does not provide cloud accounts, and does not proxy video traffic. It may reuse the same category of external tools already proven elsewhere: yt-dlp, ffmpeg, local ASR, browser cookies, and model APIs.

## Core Principles

- Convert video into a scannable knowledge map, not only a summary.
- Preserve enough detail that the deepest text view can substitute for watching the video when time is limited.
- Keep the default workflow fast for working professionals. Do not force classroom-style answers, long quizzes, or heavy review rituals.
- Bind course-derived claims to transcript segments and timestamps whenever possible.
- Clearly separate course-derived content from AI-added context.
- Default to streaming or embedded playback, with optional local caching for important videos.
- Keep all first-version data local.

## User Workflow

1. User enters a course or video URL.
2. User selects an extraction mode:
   - normal yt-dlp access,
   - use browser login state through cookies-from-browser,
   - use a cookies file.
3. Course Navigator extracts metadata and subtitles through yt-dlp.
4. If the source requires login, CAPTCHA, or manual page interaction, the user completes that outside the automatic flow and then retries extraction.
5. If subtitles exist, the app normalizes them into transcript segments.
6. If subtitles do not exist, a later version may extract audio with ffmpeg and run local ASR.
7. The app generates AI study material from the transcript.
8. The app opens a study workspace with video, transcript, and AI learning views linked by timestamp.

## Playback Model

The app supports two playback sources behind a single player contract:

- WebEmbedPlayer: default. Uses YouTube iframe when possible, or an embeddable page/source for other providers. It may degrade when a provider blocks iframe control.
- LocalFilePlayer: optional. Downloads video through yt-dlp and plays it through HTML5 video. This offers the strongest control but consumes disk and bandwidth.

Both players expose the same behavior to the UI:

- play
- pause
- seek(seconds)
- current time updates

Transcript and AI notes depend only on timestamps, not on the concrete player type. Switching source preserves the current timestamp.

## AI Content Levels

The AI result is a layered reading system:

- L0 One-line judgment: what the lesson is about and whether it is worth watching now.
- L1 Time map: large timestamp ranges that show what each block covers.
- L2 Structured outline: collapsible chapters, concepts, arguments, examples, and advice.
- L3 Detailed notes: preserves explanation flow, examples, terminology, and causal links.
- L4 High-fidelity text lesson: a detailed text reconstruction that avoids over-compression and preserves sequence, conditions, examples, exceptions, and explanation detail.

L1 is optimized for quick scanning. L4 is optimized for replacing full video viewing when necessary.

## AI Boundaries

Course-derived content must be based on transcript, title, metadata, and user-provided material. It should include timestamps.

AI-added context must be labeled separately. It may explain terminology, background, possible caveats, and learning suggestions, but it must not pretend to be course source material.

Uncertain transcript spans, ASR issues, or model uncertainty must be marked as uncertain. Uncertain text should not be used for quote cards.

## First-Version Scope

P0:

- URL input.
- yt-dlp metadata and subtitle extraction.
- browser cookies and cookies file support.
- transcript normalization.
- YouTube embed playback.
- transcript click-to-seek.
- L1-L4 AI material display with timestamp seek.
- local JSON persistence.

P1:

- optional local video download.
- local file playback and source switching.
- settings for model provider, model, base URL, and API key.
- lightweight thought prompts and review suggestions.

Out of scope for the first usable version:

- cloud account system.
- cloud sync.
- browser extension.
- cross-video knowledge base.
- image generation cards.
- full spaced repetition system.
- automatic CAPTCHA or login bypass.

## UI Model

The app is a dense, calm research workspace:

- top bar: URL input, extraction mode, status, settings.
- left column: source/task list and large-block time map.
- center column: player and transcript.
- right column: AI learning views with tabs for Guide, Outline, Detailed, and High Fidelity.

The UI should feel like an editor or study cockpit, not a marketing page. Priorities are alignment, scan speed, compact hierarchy, readable typography, and reliable timestamp navigation.

## Safety

- Do not delete files outside the project data directory.
- Do not install global dependencies during normal setup.
- Store local app data under the project runtime data directory by default.
- Store API keys in local environment/config files excluded from public docs and never print them in logs.
- Any dependency installation must be project-local unless the user explicitly approves otherwise.

## Test Samples

- Public or cookie-enabled YouTube URL: `https://www.youtube.com/watch?v=JPcx9qHzzgk&t=13s`
- Login-gated DeepLearning.AI URL: kept as a realistic manual-login scenario.

