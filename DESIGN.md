# x-video-subtitle — 设计文档

独立 skill:把一段视频(尤其 X 下载的英文视频)转成**中英双语硬字幕**成品。
ASR → 切分 → 翻译(保轴)→ 双语 ASS → libass 烧录。产物止于成品视频,人工可在中途检查点改字幕。

> 归属:按主项目 [ADR 0007](../../../tangka-code/good-script/wechat-official-account/docs/adr/0007-phase2-skills-architecture.md)「源/IO + 外部重依赖 → 独立 skill」。x-post-cover 只负责把 `video.mp4` 采进素材库 `media/`,本 skill 独立消费任意视频路径(不限 X)。

## 已定决策(2026-06-04)

1. **双语**:中英双语,中文在上(大)、英文在下(小)。
2. **ASR 引擎**:**faster-whisper**(词级时间戳 → 精细切句 + Silero VAD 去静音)。
3. **形态**:独立新 skill `x-video-subtitle`(本目录),不并进 x-post-cover。

## 数据流

```
video.mp4
  │ ① ASR        faster-whisper large-v3, word_timestamps=True, vad_filter=True, task=transcribe
  ▼
segments[] (en, 词级时间戳)
  │ ② 切分整形    按标点 + 词级时间戳重排成字幕 cue(≤~42 拉丁字/cue, 1.0–6.0s, 合并 <0.8s, 边界吸附到词)
  ▼
cues[] = [{start, end, en}]
  │ ③ 翻译(保轴) DeepSeek,[N] 序号对齐,保持 cue 数不变,术语留英文
  ▼
cues[] = [{start, end, en, zh}]
  │ ④ 生成        写 video.en.srt(留档) + video.zh.ass(双语两行/cue)
  ▼
video.zh.ass   ◀── 【人工检查点:可用 Aegisub / 文本编辑器改错词、断句、时间】
  │ ⑤ 烧录        ffmpeg -vf "ass=video.zh.ass" -c:v libx264 -crf 18 -c:a copy
  ▼
video.zh-hardsub.mp4
```

## 两段式 CLI(人工把关)

| 命令 | 做 | 产出 |
|---|---|---|
| `prep <video> [--model large-v3] [--lang en]` | ①②③④ | `*.en.srt` + `*.zh.ass` |
| `burn <video> [ass]` | ⑤ | `*.zh-hardsub.mp4` |
| `run  <video>` | prep + burn 一把过 | 全部 |

不改字幕也能 `run` 直出;改字幕则 `prep` → 手改 `.zh.ass` → `burn`。

## 双语 ASS 样式

- 两个 Style:`ZH`(PingFang/STHeiti,高度 ~5.2%,白字黑描边 ~2.5px,`\an2` 底部居中,MarginV 较大=偏上)、`EN`(Helvetica Neue,高度 ~3.4%,浅灰 `&H00DDDDDD`,MarginV 较小=偏下)。
- 每个 cue 写**两行 Dialogue**(同时间码,ZH 一行 + EN 一行,靠 MarginV 错开上下)。
- `PlayResX/Y` 设为视频实际宽高,字号按比例随分辨率缩放。
- **描边字**(非底框):主流、清晰、libass 原生;不做圆角底框(那是旧 PIL 方案的唯一卖点,换 libass 即舍弃)。

## 字体(本机实测)

- 系统**没有** PingFang 系统字体文件(只在某 electron app 的 workaround 目录里);系统可用 CJK 为 **`STHeiti Medium.ttc`**(旧 burn 脚本也用它)。
- 默认:ZH = `STHeiti Medium`,EN = `Helvetica Neue`。可用 env 覆盖。libass 经 fontconfig 按名解析;必要时 `ass=...:fontsdir=/System/Library/Fonts`。

## ⚠️ 前置依赖:ffmpeg 必须带 libass(当前缺!)

- 本机 `/opt/homebrew/bin/ffmpeg` 8.1 **没有 `ass`/`subtitles` 滤镜**(实测 `ffmpeg -h filter=ass` → Unknown filter)。**这很可能就是旧脚本走 PIL 逐帧合成的根因**(没 libass 只能手画)。
- 主流烧录依赖 libass。落地前先修:
  ```bash
  brew reinstall ffmpeg          # 标准 formula 带 libass+fontconfig+freetype+harfbuzz
  ffmpeg -h filter=ass | head -1 # 验证不再 Unknown
  ```
- 已用 `ffmpeg-full` 装好 libass,烧录走 libass 单遍过;旧的 PIL 逐帧脚本(burn-zh-subtitles.py)已废弃删除。

## 依赖与配置

- **运行时**:Python ≥3.9;`pip install faster-whisper`(CTranslate2,Apple Silicon 跑 CPU int8/float16);`ffmpeg`(带 libass);DeepSeek key。
- **模型**:`large-v3`(~3GB)。⚠️ **国内网络 + 公司代理下,`huggingface_hub` 库自动下载会在 etag HEAD 阶段失败**(`LocalEntryNotFoundError`)。可靠做法:用 curl 从 `https://hf-mirror.com/Systran/faster-whisper-<size>/resolve/main/{config.json,tokenizer.json,vocabulary.txt,model.bin}` 直下到本地目录(经 http 代理 200 通),再 `WHISPER_MODEL=<本地目录> HF_HUB_OFFLINE=1` 离线加载。env `WHISPER_MODEL` 也可指向目录或调小模型。
- **语言**:本 skill 用 Python(faster-whisper 是 Python;翻译/ffmpeg 编排都放 Python)。
- **`.env`**:`DEEPSEEK_API_KEY`(与 x-post-cover 同一个 key)、`WHISPER_MODEL`、`ZH_FONT`、`EN_FONT`、`TARGET_LANG`(默认 zh)。

## 翻译保轴(③ 细节)

- 不逐句裸译(丢上下文→割裂)。沿用 x-post-cover/scrape.ts 的 `[N]` 对齐法:把全部 cue 文本带序号一次性发 DeepSeek,要求**保持行数、按序号回填**;术语(Codex/ChatGPT/token…)留英文。
- 译文行数与 cue 数必须一致;不一致则报错回退(宁可报错也不错位)。

## 产物布局(接素材库)

```
素材库/<date>_<handle>_<id>/
  cover.png
  content.md
  media/
    video.mp4
    video.en.srt          # whisper 转写留档
    video.zh.ass          # 双语字幕(人工检查点)
    video.zh-hardsub.mp4  # 成品
```

## SKILL.md(实现期再写)

- `user-invocable`,`/x-subtitle <video-path>`(给 X URL 时可先 yt-dlp 或由 x-post-cover 采)。
- bootstrap:检查 faster-whisper 已装、ffmpeg 带 libass、DEEPSEEK_API_KEY;缺则提示安装/配置。

## 端到端验证(2026-06-04 已通过)

用 `https://x.com/OpenAI/status/2062249312839434452`(90s 1080p)全链路跑通:yt-dlp 下载 → faster-whisper(base)转写 12 段 → DeepSeek 译 12/12 → 双语 ASS → libass 烧录 → `video.zh-hardsub.mp4`。抽帧确认「中上英下」布局正确、CJK(Heiti SC)清晰描边、英文(Helvetica Neue)在下。原型脚本:`transcribe.py` / `translate.py` / `make_ass.py`(在本目录)。`base` 模型质量糙(误听产品名),正式需 large-v3。

## 待办(实现阶段)

- [x] 修 ffmpeg(libass)前置 + 验证 → 改用 `ffmpeg-full`,已验证
- [x] 链路三段原型(transcribe/translate/make_ass)跑通
- [ ] 下 large-v3 模型(curl + hf-mirror)重跑,核对字幕质量
- [ ] `prep`:faster-whisper 转写 + 切分 + DeepSeek 译 + 写 srt/ass
- [x] `burn`:libass 烧录
- [ ] `run` 编排 + SKILL.md + .env.example + README
- [ ] 主项目补 ADR 0008(记录本 skill 与三项决策)
