# Course Navigator

[中文说明](README.md)

![Course Navigator banner](docs/images/course-navigator-banner-en.jpg)

Course Navigator is a video course workspace that turns subtitles into a navigable study experience. Paste a supported video URL or import a local video, extract subtitles, review the transcript beside the video, organize lessons into collections, and use AI to translate, analyze, and correct ASR text.

It is built for learners, researchers, and course-heavy teams who need to understand long videos quickly, keep courses organized, and jump back to the right moment without scrubbing through hours of playback.

## Interface Preview

![Course Navigator video course workspace](docs/images/course-navigator-workspace.jpg)

## Highlights

- Build a course library with collections, lesson titles, ordering, local video imports, and local video cache controls.
- Import and export lightweight course packages for sharing organized courses, corrected subtitles, translated subtitles, and AI study material.
- Extract subtitles from supported video pages with `yt-dlp`, or use local ASR, online ASR, or a local subtitle upload.
- Manage active course material in a dedicated workspace, including course records, AI study material, and local video files; runtime extraction files and settings stay in the local runtime directory.
- Online ASR supports xAI, OpenAI Whisper, Groq Whisper, and custom compatible endpoints.
- Use direct access, browser login, or a cookies file for videos that require authentication.
- Watch supported videos with clickable transcripts, bilingual subtitle views, and timestamp navigation.
- Generate AI study material, including a guide, outline, interpretation, and detailed notes.
- Regenerate the guide, outline, interpretation, or detailed notes independently when only one section needs updating.
- Translate subtitles and titles.
- Correct ASR subtitles in a dedicated review workbench with editable before/after views, hover review cards, confidence scores, accept/reject controls, confidence sorting, threshold batch acceptance, optional auto-save, and a second correction pass.
- Add your own reference terms, names, product names, and common recognition errors before ASR correction.
- Optionally validate ASR correction candidates with Tavily or Firecrawl.
- Use one shared model profile library for translation, study generation, and ASR correction, with OpenAI-compatible and Anthropic formats.

## What's New

- Local video import: import local videos from the top toolbar, keep them in the course workspace, and play them immediately in local mode. Imported videos can use local ASR or online ASR for subtitle generation.
- Workspace management: active course material now lives in a dedicated workspace. Course records, AI study material, and active video files are managed with the course, while extraction work files and app settings stay in the runtime data directory.
- Local video cleanup: local imported courses no longer expose a separate cache-removal action. Deleting the course removes both the course record and the imported video file; downloaded caches for online courses can still be removed independently.
- Subtitle sources: local subtitle upload and online ASR are now supported. Online ASR extracts audio, compresses it, splits it when needed, and returns timestamped subtitles for videos without platform captions.
- Online ASR setup: choose xAI, OpenAI Whisper, Groq Whisper, a custom endpoint, or “Do not use online ASR.” Provider changes are saved immediately, and ASR prefers the source video language when it is available.
- Local ASR improvements: extraction now shows progress, and Chinese output is normalized to Simplified Chinese.
- Course package sharing: choose individual courses or full collections from the library and export a lightweight share package. Packages include video links, corrected subtitles, translated subtitles, AI study material, and an optional note. They do not include local video caches or model profiles. Full collections keep their collection name and lesson order when imported.
- Better ASR search validation: search results are first synthesized into background information, then used together with video metadata and user reference text for the final correction pass. This helps reduce incorrect edits caused by outdated model knowledge.
- Improved ASR review flow: suggestion navigation, linked before/after scrolling, hover review cards, confidence sorting, threshold acceptance, and optional auto-save after accepting suggestions.
- Library refinements: collection ordering and collection deletion are supported; deleting a course also cleans up related local cache files.

## Requirements

- Node.js 20 or newer, with npm.
- Python 3.11 or newer.
- `uv` for Python dependency management.
- `ffmpeg`, optional at startup but needed for local video cache, audio extraction, and media conversion.
- `curl`, used by the start script to check service readiness.

`yt-dlp` is installed with the Python project dependencies.

The app can start without `ffmpeg`. If you use media cache or local audio workflows, install it with your system package manager, for example:

```bash
# macOS
brew install ffmpeg

# Ubuntu or Debian
sudo apt install ffmpeg

# Windows
winget install Gyan.FFmpeg
```

## Quick Start

```bash
git clone https://github.com/Liu-Bot24/course-navigator.git
cd course-navigator
npm start
```

The start command installs dependencies, creates local settings when needed, starts the API, and starts the web app. If `ffmpeg` is missing, startup shows a warning and continues.

Open:

```text
http://127.0.0.1:5173
```

Press `Ctrl+C` in the terminal to stop both services.

## AI Setup

Course Navigator can extract, browse, and manually edit subtitles without an AI model. AI translation, study generation, and ASR correction need at least one model profile.

In the app settings, create a model profile, choose a provider format, enter the API address, model name, and API key, then assign profiles to the tasks you want to use:

| Task | What it does |
| --- | --- |
| Subtitle model | Subtitle and title translation. |
| Study model | Interpretation and detailed study text. |
| Structure model | Context summaries, semantic blocks, guide, and outline. |
| ASR correction model | ASR correction suggestions in the correction workbench. |

Model profiles support:

| Provider format | Typical API address |
| --- | --- |
| OpenAI compatible | `https://api.openai.com/v1` or another compatible endpoint |
| Anthropic | `https://api.anthropic.com/v1` or a compatible Anthropic endpoint |

The app also reads optional environment settings:

| Setting | Controls | Default |
| --- | --- | --- |
| `COURSE_NAVIGATOR_WORKSPACE_DIR` | Course workspace for records, AI study material, imported videos, and local video caches | `course-navigator-workspace` |
| `COURSE_NAVIGATOR_DATA_DIR` | Local runtime data for subtitle extraction and ASR work files | `.course-navigator` |
| `COURSE_NAVIGATOR_LLM_BASE_URL` | Optional single-profile API address | Empty |
| `COURSE_NAVIGATOR_LLM_API_KEY` | Optional single-profile API key | Empty |
| `COURSE_NAVIGATOR_LLM_MODEL` | Optional single-profile model name | Empty |
| `COURSE_NAVIGATOR_ASR_SEARCH_ENABLED` | Enables search-assisted ASR correction | `false` |
| `COURSE_NAVIGATOR_ASR_SEARCH_PROVIDER` | Search provider for ASR validation | `tavily` |
| `COURSE_NAVIGATOR_ASR_SEARCH_RESULT_LIMIT` | Search results per query | `5` |
| `COURSE_NAVIGATOR_TAVILY_API_KEY` | Tavily API key | Empty |
| `COURSE_NAVIGATOR_FIRECRAWL_BASE_URL` | Firecrawl API address | Empty |
| `COURSE_NAVIGATOR_FIRECRAWL_API_KEY` | Firecrawl API key | Empty |
| `COURSE_NAVIGATOR_ONLINE_ASR_PROVIDER` | Online ASR provider: `none`, `xai`, `openai`, `groq`, or `custom` | `none`; a configured key can be selected automatically |
| `COURSE_NAVIGATOR_XAI_ASR_API_KEY` | xAI online ASR API key | Empty |
| `COURSE_NAVIGATOR_OPENAI_ASR_API_KEY` | OpenAI Whisper API key | Empty |
| `COURSE_NAVIGATOR_GROQ_ASR_API_KEY` | Groq Whisper API key | Empty |
| `COURSE_NAVIGATOR_CUSTOM_ASR_BASE_URL` | Custom online ASR endpoint | Empty |
| `COURSE_NAVIGATOR_CUSTOM_ASR_MODEL` | Custom online ASR model name | Empty |
| `COURSE_NAVIGATOR_CUSTOM_ASR_API_KEY` | Custom online ASR API key | Empty |

Firecrawl can use either the hosted service or a self-hosted service:

| Mode | Firecrawl address | API key |
| --- | --- | --- |
| Hosted Firecrawl | `https://api.firecrawl.dev` | Use the API key from the Firecrawl dashboard |
| Self-hosted Firecrawl | Your Firecrawl service address, for example `http://192.168.1.10:3002` | Fill this in if your self-hosted service requires authentication; otherwise leave it empty |

You can enter the service root URL. Course Navigator uses the `/v1/search` endpoint for search requests, so `https://api.firecrawl.dev` becomes `https://api.firecrawl.dev/v1/search`.

Online ASR can be configured in the app settings. Preset providers only need an API key; custom endpoints need a base URL, model name, and API key. ASR tries to produce subtitles in the source video language; translation remains a separate subtitle translation step.

The startup script supports custom local ports:

| Setting | Controls | Default |
| --- | --- | --- |
| `COURSE_NAVIGATOR_API_HOST` | API host | `127.0.0.1` |
| `COURSE_NAVIGATOR_API_PORT` | API port | `8000` |
| `COURSE_NAVIGATOR_WEB_HOST` | Web app host | `127.0.0.1` |
| `COURSE_NAVIGATOR_WEB_PORT` | Web app port | `5173` |

## Video Access

Course Navigator supports three extraction modes:

| Mode | Use when |
| --- | --- |
| Normal | The video is public and can be accessed directly. |
| Browser login | The video works in your browser and needs your logged-in session. |
| Cookies file | You already have an exported cookies file for the site. |

Supported sites, subtitle languages, and automatic captions depend on `yt-dlp` and the source platform.

## Subtitle Sources

| Source | Use when |
| --- | --- |
| Source first | Prefer platform subtitles and fall back to local ASR when they are missing. |
| Local ASR | Generate timestamped subtitles on your machine. |
| Online ASR | Generate timestamped subtitles with a configured online speech-to-text service. |
| Local upload | Upload an existing TXT, MD, SRT, VTT, or similar subtitle text file. |

## Course Management

The library can group videos into collections, edit course and collection names, adjust lesson order, copy source links, remove records, and manage downloaded caches for online courses. For imported local videos, the video file is part of the course material; deleting the course also deletes that imported video file. Collections are useful for playlists, lecture series, interviews, or any long-running learning project.

## AI Study Material

After subtitles are available, Course Navigator can generate study material in the selected output language:

- Guide: prerequisites, prompts, review suggestions, and a quick orientation.
- Outline: a navigable structure linked to video timestamps.
- Interpretation: explanatory notes for the main learning blocks.
- Detailed notes: a fuller text version for careful review.

Each section can be regenerated independently, so you can refresh only the part that needs improvement.

## ASR Correction

The ASR correction workbench is designed for subtitles created by automatic speech recognition. It works with the same model profile library as the main workspace.

![ASR correction workbench](docs/images/course-navigator-asr-correction.jpg)

You can:

- edit the subtitle text directly,
- add reference information for known terms, people, products, and common ASR mistakes,
- generate targeted AI correction suggestions,
- compare the original text and corrected preview side by side,
- hover highlighted changes to see the reason, evidence, and accept/reject controls,
- review all suggestions in the side panel,
- sort by confidence,
- accept all suggestions above a confidence threshold,
- auto-save accepted suggestions when you enable that option,
- run another AI correction pass after manual edits or accepted changes,
- enable Tavily, hosted Firecrawl, or self-hosted Firecrawl search validation when a correction needs external evidence.

Accepted changes can be saved back to the main video workspace so the corrected subtitles become the active transcript.

## Manual Commands

The one-command start is recommended. If you prefer separate terminals:

```bash
uv sync
npm install
npm run dev:api
```

Then in another terminal:

```bash
npm run dev
```

## Privacy And Data

Course Navigator stores course records, generated study material, imported videos, and local video caches in your course workspace. Subtitle extraction files, ASR work files, and local settings are kept in the local runtime data directory. The first time the new workspace is used, Course Navigator copies course records and local video caches from the old data directory into the workspace.

When you use AI translation, study generation, or ASR correction, the relevant transcript text and context are sent to the model provider you configured. When search-assisted ASR correction is enabled, search queries are sent to the search provider you configured. Keep API keys on your own machine and use providers you trust.

See [PRIVACY.md](PRIVACY.md) for the full privacy notes.

## License And Security

Course Navigator is released under the [MIT License](LICENSE). See [SECURITY.md](SECURITY.md) for security reporting and responsible disclosure.
