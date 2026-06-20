# x-video-subtitle — 设计文档

独立 skill:把一段视频(尤其 X/Twitter 下载的英文视频)转成**中英双语硬字幕**成品。
ASR → 切分 → 翻译(保轴)→ 双语 ASS → libass 烧录。产物止于成品视频,人工可在中途检查点改字幕。

## 设计决策

1. **双语**:中英双语,中文在上(大)、英文在下(小)。
2. **ASR 引擎**:**faster-whisper**(词级时间戳 → 精细切句 + Silero VAD 去静音)。
3. **形态**:独立 skill `x-video-subtitle`,既能作为 Codex skill 使用,也能命令行直跑。

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
- **描边字**(非底框):主流、清晰、libass 原生;不做圆角底框,保持烧录链路简单稳定。

## 字体

- 默认:ZH = `STHeiti Medium`,EN = `Helvetica Neue`。可用 env 覆盖。libass 经 fontconfig 按名解析;必要时可给 `ass` 滤镜传 `fontsdir`。
- 不同系统的中文字体名称可能不同,建议先用默认值测试一条短视频;如中文字体回退不理想,再设置 `ZH_FONT`。

## 前置依赖:ffmpeg 必须带 libass

- 主流字幕烧录依赖 libass。安装后先验证 `ass` 滤镜可用:
  ```bash
  brew install ffmpeg-full
  ffmpeg -h filter=ass | head -1 # 验证不再 Unknown
  ```

## 依赖与配置

- **运行时**:Python ≥3.9;`pip install faster-whisper`(CTranslate2,Apple Silicon 跑 CPU int8/float16);`ffmpeg`(带 libass);DeepSeek key。
- **模型**:`large-v3`(~3GB)。可让 faster-whisper 自动下载;网络不稳定时,可用 curl 从 `https://hf-mirror.com/Systran/faster-whisper-<size>/resolve/main/{config.json,tokenizer.json,vocabulary.txt,model.bin}` 直下到本地目录,再 `WHISPER_MODEL=<本地目录> HF_HUB_OFFLINE=1` 离线加载。env `WHISPER_MODEL` 也可指向目录或调小模型。
- **语言**:本 skill 用 Python(faster-whisper 是 Python;翻译/ffmpeg 编排都放 Python)。
- **`.env`**:`DEEPSEEK_API_KEY`、`LIBRARY`、`WHISPER_MODEL`、`ZH_FONT`、`EN_FONT`、`TARGET_LANG`(默认 zh)。

## 翻译保轴(③ 细节)

- 不逐句裸译(丢上下文→割裂)。使用 `[N]` 对齐法:把全部 cue 文本带序号一次性发 DeepSeek,要求**保持行数、按序号回填**;术语(Codex/ChatGPT/token…)留英文。
- 译文行数与 cue 数必须一致;不一致则报错回退(宁可报错也不错位)。
- 中文短视频字幕风格已固化进 prompt:中文要短、自然、少直译腔;`skill` 保留英文;常用 Codex 术语固定为“电脑操作 / 浏览器操作 / 你连接的插件 / 线程 / 元数据 / 字幕 / 缩略图 / 视频包”。
- ASR 常把一句话切成上下半句,例如第一条 cue 结尾是 `turn what it`,第二条才是 `learns into a skill...`。翻译 prompt 明确要求**碎片行也必须给中文续句**,脚本也把“缺行或空中文行”视为失败并重试一次,避免烧出只有英文的空中文字幕。
- 翻译后还有一层轻量 `polish_zh()` / `normalize_en()`:把“计算机使用/计算机操作”收敛为“电脑操作”,“浏览器使用”收敛为“浏览器操作”,“技能”在 skill 语境下收敛为 `skill`,并把 ASR 常见误写 `CHAT-GPT`/`CHAT GPT`/`OPEN AI` 收敛为 `ChatGPT`/`OpenAI`。这层只做窄替换,避免大面积改坏译文。

## 产物布局

```
~/x-video-subtitle-library/<date>_<handle>_<id>/
  media/
    video.mp4
    video.en.srt          # whisper 转写留档
    video.zh.ass          # 双语字幕(人工检查点)
    video.zh-hardsub.mp4  # 成品
```

## Skill 入口

- `user-invocable`,`/x-subtitle <video-path-or-x-url>`。
- bootstrap:检查 faster-whisper 已装、ffmpeg 带 libass、DEEPSEEK_API_KEY;缺则提示安装/配置。

## 端到端验证

推荐用一条 10 到 30 秒的公开英文视频先跑通:yt-dlp 下载 → faster-whisper 转写 → DeepSeek 翻译 → 双语 ASS → libass 烧录 → `video.zh-hardsub.mp4`。随后抽帧确认「中文在上、英文在下」布局正确、中文字体清晰描边、字幕没有贴边或遮挡主体。

## 维护清单

- [x] `prep`:faster-whisper 转写 + DeepSeek 翻译 + 写 srt/ass
- [x] `burn`:libass 烧录
- [x] `run`:prep + burn 一把过
- [x] Codex `SKILL.md` bootstrap + README + `.env.example`
- [ ] 增加更多语言和字幕样式 preset
