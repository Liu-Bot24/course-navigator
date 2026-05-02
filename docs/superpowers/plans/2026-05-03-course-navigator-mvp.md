# Course Navigator MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a usable local Course Navigator MVP with URL extraction, transcript normalization, AI study material generation, YouTube embed playback, transcript seeking, and timestamp-linked AI views.

**Architecture:** Use a FastAPI backend for local media extraction, persistence, and AI calls. Use a React + Vite frontend for the study workspace. Keep the backend independent from Hermes/OpenClaw and communicate through JSON APIs.

**Tech Stack:** Python 3.11+ via uv, FastAPI, pydantic, pytest, React, TypeScript, Vite, Vitest, CSS modules/plain CSS, yt-dlp, ffmpeg.

---

## File Structure

- `pyproject.toml`: backend package, Python dependencies, pytest config.
- `package.json`: frontend scripts and npm dependencies.
- `backend/course_navigator/app.py`: FastAPI application and route registration.
- `backend/course_navigator/config.py`: local settings loading and safe defaults.
- `backend/course_navigator/models.py`: Pydantic request/response models.
- `backend/course_navigator/subtitles.py`: VTT/SRT parsing and transcript normalization.
- `backend/course_navigator/ytdlp.py`: yt-dlp subprocess wrapper.
- `backend/course_navigator/library.py`: local JSON persistence for course items.
- `backend/course_navigator/ai.py`: provider-neutral AI study material generator.
- `backend/tests/`: backend tests.
- `frontend/index.html`: Vite entry HTML.
- `frontend/src/`: React UI, API client, player abstraction, sample state, styles.
- `.env.example`: local model provider configuration example.
- `.gitignore`: local data, env files, caches, dependencies.

## Tasks

### Task 1: Project Skeleton

- [ ] Create backend and frontend package files.
- [ ] Create `.gitignore` and `.env.example`.
- [ ] Install project-local dependencies with `uv sync` and `npm install`.
- [ ] Run empty backend and frontend test commands.

### Task 2: Transcript Parser

- [ ] Write failing pytest cases for VTT and SRT parsing.
- [ ] Implement `parse_subtitle_text` returning normalized transcript segments.
- [ ] Verify tests pass.

### Task 3: yt-dlp Wrapper

- [ ] Write failing pytest cases using monkeypatched subprocess calls.
- [ ] Implement metadata/subtitle extraction command building with normal, cookies file, and browser cookies modes.
- [ ] Verify tests pass.

### Task 4: Local Library Persistence

- [ ] Write failing pytest cases for creating and reading a course item.
- [ ] Implement safe project-local JSON persistence.
- [ ] Verify tests pass.

### Task 5: AI Study Material

- [ ] Write failing tests for fallback deterministic study material.
- [ ] Implement a deterministic local generator when no API key is configured.
- [ ] Implement an OpenAI-compatible chat completions adapter for configured providers.
- [ ] Verify tests pass without external API.

### Task 6: FastAPI Routes

- [ ] Write route tests for health, extraction, item retrieval, and AI generation.
- [ ] Implement API routes.
- [ ] Verify backend tests pass.

### Task 7: Frontend Data Model and API Client

- [ ] Write Vitest tests for API client URL construction and time formatting utilities.
- [ ] Implement frontend types, utilities, and API client.
- [ ] Verify frontend tests pass.

### Task 8: Main Study Workspace UI

- [ ] Build the app shell: top bar, left time map, center player/transcript, right AI tabs.
- [ ] Implement YouTube iframe embed for YouTube URLs.
- [ ] Implement transcript click-to-seek through player state.
- [ ] Implement AI note click-to-seek.
- [ ] Verify in browser on desktop and mobile widths.

### Task 9: Local Download Hook

- [ ] Add backend route for optional video download command creation/execution.
- [ ] Add UI button for local caching.
- [ ] Add local player source state and source switching.
- [ ] Verify source switching preserves timestamp.

### Task 10: End-to-End Smoke Test

- [ ] Start backend and frontend dev servers.
- [ ] Load the app in browser.
- [ ] Use a sample transcript or extracted subtitles to generate study material.
- [ ] Verify transcript and AI nodes seek the player.
- [ ] Run backend tests, frontend tests, and frontend build.

