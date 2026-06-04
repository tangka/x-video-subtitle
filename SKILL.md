---
name: x-subtitle
description: Turn a video into a bilingual (Chinese-over-English) hard-subtitled MP4. Use when the user has a video file (especially an English X/Twitter video) and wants burned-in Chinese+English subtitles. Transcribes with faster-whisper, translates with DeepSeek, burns with ffmpeg/libass.
user-invocable: true
---

把视频做成**中英双语硬字幕**成品(中文在上、英文在下)。链路:faster-whisper 转写 → DeepSeek 翻译 → libass 烧录。

## Step 1 — bootstrap check

```bash
SKILL_DIR="$HOME/.claude/skills/x-video-subtitle"
[ -d "$SKILL_DIR" ] || SKILL_DIR="$HOME/Code/scripts/x-video-subtitle"
miss=""
grep -q '^DEEPSEEK_API_KEY=' "$SKILL_DIR/.env" 2>/dev/null || miss="$miss DEEPSEEK_API_KEY"
ffmpeg -hide_banner -h filter=ass 2>&1 | grep -q "Unknown filter" && miss="$miss ffmpeg-libass"
[ -f "$SKILL_DIR/.models/large-v3/model.bin" ] || miss="$miss whisper-model"
command -v uv >/dev/null || miss="$miss uv"
echo "SKILL_DIR=$SKILL_DIR"
[ -z "$miss" ] && echo "READY" || echo "NEEDS:$miss"
```

## Step 2 — act on the result

**If `NEEDS:` lists items**, fix them (see `$SKILL_DIR/DESIGN.md` / `README.md`):
- `DEEPSEEK_API_KEY` → 写进 `$SKILL_DIR/.env`(可复用 x-post-cover 的 key)。
- `ffmpeg-libass` → `brew install ffmpeg-full && brew unlink ffmpeg && brew link --overwrite ffmpeg-full`。
- `whisper-model` → curl 从 hf-mirror 下 large-v3 到 `$SKILL_DIR/.models/large-v3/`(见 README)。
- `uv` → `brew install uv` 或 `curl -LsSf https://astral.sh/uv/install.sh | sh`。

**If `READY`**, 跑(`$ARGUMENTS` 可为**本地视频路径**或 **X 推文链接**,可选 `--trim-tail 2` 掐尾防侵权):

```bash
cd "$SKILL_DIR"
uv run --python 3.11 --with faster-whisper subtitle.py run $ARGUMENTS
```

给 X 链接时会先 yt-dlp 下载到 `素材库/<date>_<handle>_<id>/`(按 `_<推文id>` 复用 x-post-cover 已建的同一文件夹),需 `http(s)_proxy`、私有视频需 Chrome 登录态。产物落在视频同目录:`<base>.en.srt`(转写留档)、`<base>.zh.ass`(双语字幕,**发布前可手改错词**)、`<base>.zh-hardsub.mp4`(成品)。

**两段式(要人工校字幕时)**:先 `subtitle.py prep <video>` → 用编辑器/Aegisub 改 `<base>.zh.ass` → 再 `subtitle.py burn <video> [--trim-tail 2]`。

报告产物路径;失败则报错误。
