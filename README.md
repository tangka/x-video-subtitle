# x-video-subtitle

视频 → **中英双语硬字幕**成品(中文在上、英文在下)。Claude Code skill,也可命令行直跑。

```
faster-whisper 转写 → DeepSeek 翻译(保轴)→ 双语 ASS → ffmpeg/libass 烧录
```

## 用法

```bash
# 一把过(转写+翻译+烧录)
uv run --python 3.11 --with faster-whisper subtitle.py run video.mp4 --trim-tail 2

# 或两段式(要人工校字幕):
uv run --python 3.11 --with faster-whisper subtitle.py prep video.mp4   # → video.en.srt + video.zh.ass
#   ↳ 用编辑器 / Aegisub 改 video.zh.ass 里的错词、断句、时间
uv run --python 3.11 --with faster-whisper subtitle.py burn video.mp4 --trim-tail 2  # → video.zh-hardsub.mp4
```

产物落视频同目录:`*.en.srt`(转写留档)、`*.zh.ass`(字幕,**人工检查点**)、`*.zh-hardsub.mp4`(成品)。

## 依赖与安装(macOS / 国内网络)

1. **ffmpeg 带 libass**(常规 formula 不带):
   ```bash
   brew install ffmpeg-full && brew unlink ffmpeg && brew link --overwrite ffmpeg-full
   ffmpeg -h filter=ass | head -1   # 不再 Unknown 即可
   ```
2. **uv**:`brew install uv`(faster-whisper 经 uv 临时环境运行,免污染系统 Python)。
3. **whisper 模型 large-v3**(huggingface_hub 经公司代理会失败,改 curl 镜像直下):
   ```bash
   export https_proxy=http://10.40.88.38:2080 http_proxy=http://10.40.88.38:2080
   MD=.models/large-v3; mkdir -p "$MD"; b=https://hf-mirror.com/Systran/faster-whisper-large-v3/resolve/main
   for f in config.json tokenizer.json vocabulary.json preprocessor_config.json model.bin; do
     curl -sL "$b/$f" -o "$MD/$f"; done
   ```
4. **`.env`**:`cp .env.example .env`,填 `DEEPSEEK_API_KEY`(可复用 x-post-cover)。

## 配置

见 `.env.example`:`WHISPER_MODEL`(默认内置 large-v3)、`ZH_FONT`/`EN_FONT`(默认 Heiti SC / Helvetica Neue)、`TARGET_LANG_NAME`、`SUBTITLE_TRIM_TAIL`。

设计细节见 [`DESIGN.md`](DESIGN.md)。
