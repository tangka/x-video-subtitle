# /x-subtitle

Slash entry for the **x-subtitle** skill. Authoritative instructions live in `SKILL.md` at the project root — read it first.

## Routing $ARGUMENTS

| Pattern | Mode |
|---|---|
| a local video path (`*.mp4` …) | full pipeline — transcribe + translate + burn bilingual hardsub |
| an X/Twitter video URL | download first, then the full pipeline |
| `prep <video>` / `burn <video>` | two-step: prep subtitles for manual edit, then burn |
| add `--trim-tail 2` | cut the last N seconds (anti-watermark) |

Install by cloning into `~/.codex/skills/x-subtitle` or `~/.claude/skills/x-subtitle`. Needs uv, ffmpeg+libass, faster-whisper model, DEEPSEEK_API_KEY.
