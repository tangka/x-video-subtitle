# x-video-subtitle

视频 → **中英双语硬字幕**成品(中文在上、英文在下)。Codex skill,也可命令行直跑。

```
faster-whisper 转写 → DeepSeek 翻译(保轴)→ 双语 ASS → ffmpeg/libass 烧录
```

翻译层内置中文短视频字幕规范:中文短句、少直译腔;`skill` 保留英文;`computer use / browser use / connected plugins` 固定译作“电脑操作 / 浏览器操作 / 你连接的插件”;`CHAT-GPT`/`CHAT GPT` 会规整为 `ChatGPT`;ASR 切出的英文续行也必须有中文,不会静默产出空中文行。

## 给 Codex 安装

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/tangka/x-video-subtitle.git ~/.codex/skills/x-video-subtitle
```

更新:

```bash
cd ~/.codex/skills/x-video-subtitle
git pull
```

安装后重启 Codex 或开启新会话。之后可以直接说:

- “用 x-subtitle 给这个视频加中英双语硬字幕:`/path/to/video.mp4`”
- “这个 X 视频下载后加中文字幕:`https://x.com/.../status/...`”
- “先 prep,我人工校字幕后你再 burn”

## 用法

参数可以是**本地视频文件**,也可以是 **X/Twitter 链接**(自动 yt-dlp 下载,默认落 `~/x-video-subtitle-library/<date>_<handle>_<id>/`;可用 `LIBRARY` 覆盖):

```bash
# 直接喂 X 链接(下载 + 转写 + 翻译 + 烧录,一条命令)
uv run --python 3.11 --with faster-whisper subtitle.py run "https://x.com/.../status/..." --trim-tail 2

# 或本地文件
uv run --python 3.11 --with faster-whisper subtitle.py run video.mp4 --trim-tail 2

# 或两段式(要人工校字幕):
uv run --python 3.11 --with faster-whisper subtitle.py prep video.mp4   # → video.en.srt + video.zh.ass
#   ↳ 用编辑器 / Aegisub 改 video.zh.ass 里的错词、断句、时间
uv run --python 3.11 --with faster-whisper subtitle.py burn video.mp4 --trim-tail 2  # → video.zh-hardsub.mp4
```

产物落视频同目录:`*.en.srt`(转写留档)、`*.zh.ass`(字幕,**人工检查点**)、`*.zh-hardsub.mp4`(成品)。

交付前可抽帧看字幕位置:

```bash
ffmpeg -hide_banner -loglevel error -y -i video.zh-hardsub.mp4 -vf "fps=1/12,scale=480:-1,tile=4x3" -frames:v 1 /tmp/subtitle-check.jpg
```

## 依赖与安装(macOS)

1. **ffmpeg 带 libass**(常规 formula 不带):
   ```bash
   brew install ffmpeg-full && brew unlink ffmpeg && brew link --overwrite ffmpeg-full
   ffmpeg -h filter=ass | head -1   # 不再 Unknown 即可
   ```
2. **uv**:`brew install uv`(faster-whisper 经 uv 临时环境运行,免污染系统 Python)。
3. **whisper 模型 large-v3**:可让 faster-whisper 自动下载;网络不稳定时也可以手动下载到 `.models/large-v3/`:
   ```bash
   MD=.models/large-v3; mkdir -p "$MD"; b=https://hf-mirror.com/Systran/faster-whisper-large-v3/resolve/main
   for f in config.json tokenizer.json vocabulary.json preprocessor_config.json model.bin; do
     curl -sL "$b/$f" -o "$MD/$f"; done
   ```
4. **`.env`**:`cp .env.example .env`,填 `DEEPSEEK_API_KEY`。

## 配置

见 `.env.example`:`LIBRARY`、`WHISPER_MODEL`(默认内置 large-v3)、`ZH_FONT`/`EN_FONT`(默认 Heiti SC / Helvetica Neue)、`TARGET_LANG_NAME`、`SUBTITLE_TRIM_TAIL`。

设计细节见 [`DESIGN.md`](DESIGN.md)。

## 📣 关于作者 & 支持

这套工具来自我运营的两个公众号,欢迎关注 👇

- **Codexx** —— Codex 铁粉中文社区(扫下方二维码关注)
- **ClaudeDevs** —— Claude 中文社区(微信搜索「Claude 中文社区」关注)

<img src="promo/codexx-qrcode.jpg" width="160" alt="Codexx 公众号">

如果这些工具帮到你,欢迎请我喝杯咖啡 ☕

<img src="promo/wx_qr.png" width="200" alt="微信"> &nbsp;&nbsp; <img src="promo/ali_qr.png" width="200" alt="支付宝">
