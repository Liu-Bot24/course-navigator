# Course Navigator

Course Navigator is a local-first workspace for studying video courses faster. Paste a course or video URL, extract subtitles with your local `yt-dlp` setup, and turn the transcript into a timestamp-linked study map that you can scan, expand, and use to jump back into the video.

It is designed for working learners who want to quickly decide which parts of a course deserve attention, which parts can be skimmed, and where to return for review.

## What You Can Do

- Extract subtitles from supported video pages with `yt-dlp`.
- Use browser login state or a cookies file for videos that require authentication.
- Play YouTube videos through an embedded streaming player by default.
- Read and click transcript lines to jump to the matching video time.
- Generate layered study material:
  - time map,
  - collapsible outline,
  - detailed notes,
  - high-fidelity text version.
- Optionally cache important videos locally for HTML5 playback.

## Requirements

- Node.js and npm.
- Python managed by `uv`.
- `yt-dlp`.
- `ffmpeg` for future audio and local media workflows.

## Install

```bash
uv sync
npm install
```

## Run

Start the local API:

```bash
npm run dev:api
```

Start the web app in another terminal:

```bash
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Model Configuration

Course Navigator works without a model API key by generating a deterministic fallback study map. For higher-quality output, configure an OpenAI-compatible chat completions provider in `.env`.

| Setting | Controls | Default or recommended value |
| --- | --- | --- |
| `COURSE_NAVIGATOR_DATA_DIR` | Local app data directory | `.course-navigator` |
| `COURSE_NAVIGATOR_LLM_BASE_URL` | OpenAI-compatible API base URL | `https://api.siliconflow.cn/v1` |
| `COURSE_NAVIGATOR_LLM_API_KEY` | Provider API key | Keep this local |
| `COURSE_NAVIGATOR_LLM_MODEL` | Chat model for study generation | `deepseek-ai/DeepSeek-V3.2` |

Copy the example file before editing:

```bash
cp .env.example .env
```

## Access Modes

Course Navigator supports three extraction modes:

| Mode | Use when |
| --- | --- |
| Normal | The video is public and `yt-dlp` can access it directly. |
| Use browser login | The video works in your browser and `yt-dlp` should reuse browser cookies. |
| Cookies file | You already exported a cookies file for `yt-dlp`. |

## Safety Notes

Course Navigator stores generated course data locally. API keys should stay in `.env` or your shell environment. The app does not provide a public proxy and does not upload video files by default.
