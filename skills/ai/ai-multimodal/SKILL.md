---
name: ai-multimodal
description: Process and generate multimedia content using 9router (cx/gpt-5.5) for
  vision and image generation. Capabilities include analyze audio files (transcription
  with timestamps, summarization, speech understanding, music/sound analysis), understand
  images (image analysis, captioning, reasoning, object detection, design extraction,
  OCR, visual Q&A, segmentation, handle multiple images), process videos (scene detection,
  Q&A, temporal analysis), extract from documents (PDF tables, forms, charts, diagrams,
  multi-page), generate images (text-to-image with cx/gpt-5.5), generate videos (text-to-video
  with Gemini Veo fallback). Use when working with audio/video files, analyzing images
  or screenshots, processing PDF documents, extracting structured data from media,
  creating images from text prompts, or implementing multimodal AI features. Uses
  9router OpenAI-compatible API with cx/gpt-5.5 for analysis and image generation,
  Gemini Veo for video generation fallback.
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    tags:
    - multimodal
    - vision
    - image-generation
    - audio
    - video
    related_skills:
    - media-processing
    - aesthetic
---

# AI Multimodal

Analyze/generate media: non-image files (audio/video/PDF/text) via **router** (`claude-opus-4.8`, Super Kiro :8080); images via **windsurf-server** (`kimi-k2-7`→`swe-1-7`, ACP+PIL) because routers strip images. Image generation via 9router; video via Gemini Veo fallback.

## Setup

```bash
# 9router is already configured via ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY
# No additional API keys needed for analysis and image generation!

# For video generation only (optional):
export GEMINI_API_KEY="your-key"  # Get from https://aistudio.google.com/apikey

pip install openai python-dotenv pillow
```

## Quick Start

**Analyze media**: `python scripts/multimodal_process.py --files <file> --task <analyze|transcribe|extract>`
  - TIP: When asked to analyze an image, use `python scripts/multimodal_process.py --files <file> --task analyze --prompt "<your question>"`
**Generate image**: `python scripts/multimodal_process.py --task generate --prompt "description"`
**Generate video**: `python scripts/multimodal_process.py --task generate-video --prompt "description"` (requires GEMINI_API_KEY)

## Models

- **Non-image analysis** (audio/video/PDF/text): `claude-opus-4.8` via router (default, port 8080/Super Kiro)
- **Image analysis** (vision, OCR): `gpt-5.6-terra` via windsurf-server (ACP+PIL), fallback `kimi-k2-7`→`swe-1-7`
  - Both routers (9router:20130 and Super Kiro:8080) strip images from HTTP requests (`supports_image_captions=false`) — every model reached via HTTP only sees text and replies "I don't see any image".
  - windsurf-server:8083 is the ONLY path that actually analyzes images (ACP agent reads the local file with PIL/ImageMagick), so image files route there directly.
  - windsurf models can be rate-limited (~3h reset per model), time out, or return a Devin-session error — the script detects these error strings and falls through to the next model, returning a clear error only when all are exhausted (never a fake success string).
- **Image generation**: `cx/gpt-5.5` via 9router `/v1/images/generations`
- **Video generation**: `veo-3.1-generate-preview` via Gemini (fallback, requires GEMINI_API_KEY)

## Configuration

All config via environment variables (or `.env` file):
- `MULTIMODAL_MODEL`: Analysis model for non-image files (default: `claude-opus-4.8`)
- `IMAGE_GEN_MODEL`: Image generation model (default: `cx/gpt-5.5`)
- `ROUTER_BASE_URL`: router URL (default: from `ANTHROPIC_BASE_URL`, i.e. Super Kiro :8080)
- `ROUTER_API_KEY`: router API key (default: from `ANTHROPIC_API_KEY`)
- `VISION_MODELS`: Vision models for image analysis, comma-separated fallback (default: `kimi-k2-7,swe-1-7`)
- `VISION_BASE_URL`: windsurf-server URL for image analysis (default: `http://localhost:8083/v1`)
- `VISION_API_KEY`: windsurf-server API key (default: `sk-vision-local`, not checked)
- `VISION_TIMEOUT`: hard timeout per windsurf call in seconds (default: `60`) — prevents hangs
- `VISION_USE_ROUTER`: set `1` to try images via router first (usually useless — router strips images) before windsurf fallback
- `GEMINI_API_KEY`: Only for video generation fallback

## Scripts

- **`multimodal_process.py`**: CLI orchestrator for `transcribe|analyze|extract|generate|generate-video`. Non-image analysis → `claude-opus-4.8` via router; images → windsurf-server (`kimi-k2-7`→`swe-1-7`) with hard timeout + error-pattern fallback; image gen → `cx/gpt-5.5`; video → Gemini Veo fallback.
- **`gemini_batch_process.py`**: Legacy Gemini-based script (kept for backward compatibility).
- **`media_optimizer.py`**: ffmpeg/Pillow-based preflight tool that compresses/resizes/converts audio, image, and video inputs.
- **`document_converter.py`**: Converts various document formats for processing.
- **`check_setup.py`**: Verifies API configuration and dependencies.

## Examples

```bash
# Analyze an image
python scripts/multimodal_process.py --files photo.jpg --task analyze --prompt "Describe what you see"

# Transcribe audio
python scripts/multimodal_process.py --files audio.mp3 --task transcribe --prompt "Transcribe with timestamps"

# Extract data from PDF
python scripts/multimodal_process.py --files doc.pdf --task extract --prompt "Extract all tables as JSON"

# Generate an image
python scripts/multimodal_process.py --task generate --prompt "A serene mountain landscape at sunset"

# Generate a video (requires GEMINI_API_KEY)
python scripts/multimodal_process.py --task generate-video --prompt "A cat playing with a ball of yarn"
```

## Output

Results are printed as JSON. Generated images are saved to `docs/assets/`. Use `--output` to save results to a file.

## References

See `references/` directory for detailed guides on:
- Audio processing
- Image generation
- Video analysis
- Video generation
- Vision understanding
