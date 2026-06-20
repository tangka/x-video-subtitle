#!/usr/bin/env python3
"""x-video-subtitle:视频 → 中英双语硬字幕。

子命令:
  prep <video>   转写(faster-whisper)+ 翻译(DeepSeek)→ <base>.en.srt + <base>.zh.ass(人工检查点)
  burn <video>   用 <base>.zh.ass 经 libass 烧录 → <base>.zh-hardsub.mp4(可 --trim-tail 掐尾)
  run  <video>   prep + burn 一把过

依赖:faster-whisper(prep)、ffmpeg(带 libass,即 ffmpeg-full)、DEEPSEEK_API_KEY(prep 翻译)。
配置走 env / .env(见 .env.example)。设计见 DESIGN.md。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent


# ---------- 配置 ----------

def load_dotenv() -> None:
    """极简 .env 读取(不覆盖已存在的环境变量)。"""
    env = SKILL_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def resolve_model() -> str:
    """模型:env WHISPER_MODEL 优先;否则用内置 .models/large-v3(若已下载);再否则 'large-v3'。"""
    m = os.environ.get("WHISPER_MODEL")
    if m:
        return m
    local = SKILL_DIR / ".models" / "large-v3"
    if (local / "model.bin").exists():
        return str(local)
    return "large-v3"


def resolve_library() -> Path:
    """素材库根(与 x-post-cover 的 LIBRARY 同一处,落同一批推文件夹)。"""
    lib = os.environ.get("LIBRARY")
    return Path(lib).expanduser() if lib else Path.home() / "wechat-vault" / "微信公众号" / "素材库"


# ---------- X 链接 → 视频(缝1+缝3) ----------

X_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/[^/]+/status/(\d+)")


def is_x_url(s: str) -> bool:
    return bool(X_URL_RE.search(s))


def download_from_x(url: str) -> Path:
    """从 X 链接 yt-dlp 下视频到 素材库/<date>_<handle>_<id>/video.mp4。
    按 `_<推文id>` 后缀复用 x-post-cover 已建的同一文件夹(封面/正文/视频归一处)。"""
    tweet_id = X_URL_RE.search(url).group(1)  # type: ignore[union-attr]
    lib = resolve_library()
    existing = sorted(lib.glob(f"*_{tweet_id}"))
    if existing:
        folder = existing[0]
        print(f"[x] 复用素材库文件夹 {folder.name}", file=sys.stderr)
    else:
        meta = subprocess.run(
            ["uvx", "yt-dlp", "--no-playlist", "--simulate", "--print",
             "%(upload_date)s|%(uploader_id)s", url],
            capture_output=True, text=True)
        line = (meta.stdout.strip().splitlines() or [""])[-1]
        date_raw, _, handle = line.partition("|")
        date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if len(date_raw) == 8 else "0000-00-00"
        folder = lib / f"{date}_{(handle or 'x').lstrip('@')}_{tweet_id}"
        folder.mkdir(parents=True, exist_ok=True)
        print(f"[x] 新建素材库文件夹 {folder.name}", file=sys.stderr)
    media = folder / "media"
    media.mkdir(parents=True, exist_ok=True)
    video = media / "video.mp4"
    if video.exists():
        print(f"[x] 视频已存在,跳过下载", file=sys.stderr)
        return video
    print("[x] yt-dlp 下载中(需代理/可能需 Chrome 登录态)...", file=sys.stderr)
    r = subprocess.run(
        ["uvx", "yt-dlp", "--no-playlist", "--merge-output-format", "mp4",
         "-f", "bv*+ba/best", "-o", str(media / "video.%(ext)s"), url])
    if r.returncode != 0 or not video.exists():
        sys.exit("yt-dlp 下载失败(私有视频试 --cookies-from-browser chrome,或检查 http(s)_proxy)。")
    return video


def resolve_video(arg: str) -> Path:
    """参数是 X 链接就先下载,否则当本地文件。"""
    return download_from_x(arg) if is_x_url(arg) else Path(arg).resolve()


# ---------- 输出路径 ----------

def paths_for(video: str) -> dict[str, Path]:
    p = Path(video).resolve()
    stem = p.with_suffix("")
    return {
        "video": p,
        "srt": Path(f"{stem}.en.srt"),
        "ass": Path(f"{stem}.zh.ass"),
        "out": Path(f"{stem}.zh-hardsub.mp4"),
    }


def ffprobe_size(path: Path) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True, check=True)
    w, h = r.stdout.strip().split("x")
    return int(w), int(h)


def ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


# ---------- ① 转写 ----------

def transcribe(video: Path, model: str, lang: str) -> list[dict]:
    from faster_whisper import WhisperModel  # 延迟导入:burn 不需要

    print(f"[asr] model={model} lang={lang}", file=sys.stderr)
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _info = wm.transcribe(
        str(video), language=lang, task="transcribe",
        vad_filter=True, word_timestamps=True)
    cues: list[dict] = []
    for seg in segments:
        text = normalize_en(seg.text.strip())
        if not text:
            continue
        cues.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "en": text})
        print(f"  [{seg.start:6.2f}-{seg.end:6.2f}] {text}", file=sys.stderr)
    print(f"[asr] {len(cues)} cues", file=sys.stderr)
    return cues


# ---------- ② 翻译(保轴) ----------

TRANSLATION_STYLE_GUIDE = """Style guide for Chinese subtitles:
- Audience: Chinese WeChat/tech readers. Make the Chinese natural, concise, and spoken.
- Keep brand/product terms in English: Codex, ChatGPT, GPT, OpenAI, Claude, API, token, PR.
- Keep "skill" as lowercase English when it means a reusable Codex capability.
- Use these fixed terms:
  computer use = 电脑操作
  browser use = 浏览器操作
  connected plugins = 你连接的插件
  thread = 线程
  metadata = 元数据
  caption/captions = 字幕
  thumbnail = 缩略图
  upload package / video package = 视频包
  private = 私密状态
- Some ASR cues are sentence fragments. Translate every numbered line anyway; if a line is a continuation, write a short natural continuation in Chinese. Never leave a Chinese line blank.
- Prefer short subtitle phrasing. Avoid stiff literal wording like “计算机使用” or “这项技能” when “电脑操作” or “这个skill” is clearer.
"""


def normalize_en(text: str) -> str:
    """收敛 ASR 对品牌词的大小写/断字符误识别。"""
    out = re.sub(r"\bCHAT[-\s]?GPT\b", "ChatGPT", text, flags=re.I)
    out = re.sub(r"\bOPEN[-\s]?AI\b", "OpenAI", out, flags=re.I)
    return out


def build_translation_prompt(numbered: str, target: str, missing: list[int] | None = None) -> str:
    retry_note = ""
    if missing:
        retry_note = (
            "\nThe previous response missed or left blank these line numbers: "
            f"{', '.join(str(i) for i in missing)}. "
            "Retry from scratch and translate every [N], including fragments.\n"
        )
    return (
        f"Translate each numbered subtitle line into {target}. "
        "Keep the [N] numbers and the exact same number of lines. "
        "Output only the translated lines, one per [N], no extra text.\n\n"
        f"{TRANSLATION_STYLE_GUIDE}{retry_note}\n"
        f"{numbered}"
    )


def deepseek_translate(prompt: str, api_key: str) -> str:
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 1.0,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"]


def parse_numbered_translations(text: str) -> dict[int, str]:
    zh_by_idx: dict[int, str] = {}
    for part in re.split(r"(?=\[\d+\])", text):
        m = re.match(r"\[(\d+)\]\s*(.*)", part.strip(), re.S)
        if m:
            zh_by_idx[int(m.group(1))] = m.group(2).strip().replace("\n", " ")
    return zh_by_idx


def polish_zh(en: str, zh: str) -> str:
    """固定常见术语与口吻,减少每次人工改同一批词。"""
    out = re.sub(r"\s+", " ", zh).strip()
    out = normalize_en(out)
    replacements = [
        ("计算机使用", "电脑操作"),
        ("计算机操作", "电脑操作"),
        ("浏览器使用", "浏览器操作"),
        ("已连接的插件", "你连接的插件"),
        ("你的连接插件", "你连接的插件"),
        ("上传包", "视频包"),
        ("视频上传包", "视频包"),
        ("设为私人", "保存为私密状态"),
        ("设为私有", "保存为私密状态"),
        ("私有状态", "私密状态"),
    ]
    for old, new in replacements:
        out = out.replace(old, new)
    out = re.sub(r"(?<!你)连接的插件", "你连接的插件", out)

    if "skill" in en.lower():
        out = out.replace("这项技能", "这个skill")
        out = out.replace("该技能", "这个skill")
        out = out.replace("可重复使用的技能", "可复用的skill")
        out = out.replace("技能", "skill")
    return out


def translate(cues: list[dict], target: str, api_key: str) -> None:
    numbered = "\n".join(f"[{i + 1}] {c['en']}" for i, c in enumerate(cues))
    text = ""
    zh_by_idx: dict[int, str] = {}
    missing: list[int] = []
    for attempt in range(2):
        prompt = build_translation_prompt(numbered, target, missing if attempt else None)
        text = deepseek_translate(prompt, api_key)
        zh_by_idx = parse_numbered_translations(text)
        missing = [
            i + 1 for i in range(len(cues))
            if not zh_by_idx.get(i + 1, "").strip()
        ]
        if not missing:
            break
    if missing:
        sys.exit(f"译文缺行/空行 {missing},宁可报错不错位。返回:\n{text}")
    for i, c in enumerate(cues):
        c["zh"] = polish_zh(c["en"], zh_by_idx[i + 1])
    print(f"[mt] 译完 {len(cues)} 行", file=sys.stderr)


# ---------- 字幕文件 ----------

def _srt_tc(sec: float) -> str:
    ms = round(sec * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[dict], path: Path) -> None:
    """英文转写留档(SRT)。"""
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(f"{i}\n{_srt_tc(c['start'])} --> {_srt_tc(c['end'])}\n{c['en']}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")
    print(f"[srt] {len(cues)} 行 → {path.name}", file=sys.stderr)


def _ass_tc(sec: float) -> str:
    cs = round(sec * 100)
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(cues: list[dict], video: Path, out: Path, zh_font: str, en_font: str) -> None:
    """双语 ASS:中文在上(大)、英文在下(小)。单事件内 \\N + {\\rEN} 切样式,布局稳定。"""
    w, h = ffprobe_size(video)
    zh_size = round(h * 0.052)
    en_size = round(h * 0.034)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ZH,{zh_font},{zh_size},&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,1,2,40,40,42,1
Style: EN,{en_font},{en_size},&H00DDDDDD,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,42,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in cues:
        zh = c.get("zh", "").replace("\n", " ").strip()
        en = c.get("en", "").replace("\n", " ").strip()
        text = f"{zh}\\N{{\\rEN}}{en}"
        lines.append(f"Dialogue: 0,{_ass_tc(c['start'])},{_ass_tc(c['end'])},ZH,,0,0,0,,{text}")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ass] {len(cues)} 行 ({w}x{h}, ZH {zh_size}px / EN {en_size}px) → {out.name}", file=sys.stderr)


# ---------- ④ 烧录 ----------

def burn(video: Path, ass: Path, out: Path, trim_tail: float) -> None:
    if not ass.exists():
        sys.exit(f"找不到字幕 {ass},先跑 prep。")
    # libass 的 ass= 滤镜路径里逗号/冒号要转义
    ass_arg = str(ass).replace("\\", "\\\\").replace(":", r"\:").replace(",", r"\,")
    vf = f"ass={ass_arg}"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-vf", vf, "-c:v", "libx264", "-crf", "18", "-c:a", "copy",
           "-movflags", "+faststart", "-y"]
    if trim_tail > 0:
        dur = ffprobe_duration(video)
        cut = max(0.1, round(dur - trim_tail, 3))
        cmd += ["-t", str(cut)]
        print(f"[burn] 掐尾 {trim_tail}s:{dur:.2f} → {cut}", file=sys.stderr)
    cmd.append(str(out))
    # 自检:libass 是否可用
    chk = subprocess.run(["ffmpeg", "-hide_banner", "-h", "filter=ass"],
                         capture_output=True, text=True)
    if "Unknown filter" in (chk.stdout + chk.stderr):
        sys.exit("ffmpeg 不带 libass(ass 滤镜)。装 ffmpeg-full 并 link(见 DESIGN.md)。")
    subprocess.run(cmd, check=True)
    print(f"[burn] → {out.name}", file=sys.stderr)


# ---------- 命令 ----------

def cmd_prep(args) -> None:
    p = paths_for(str(resolve_video(args.video)))
    if p["ass"].exists() and not args.force:
        print(f"已存在 {p['ass'].name}(--force 覆盖);跳过 prep。", file=sys.stderr)
        return
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        sys.exit("DEEPSEEK_API_KEY 未设置(.env 或环境变量)。")
    cues = transcribe(p["video"], resolve_model(), args.src_lang)
    if not cues:
        sys.exit("转写为空(可能整段无语音)。")
    write_srt(cues, p["srt"])
    translate(cues, os.environ.get("TARGET_LANG_NAME", "Chinese"), api_key)
    build_ass(cues, p["video"], p["ass"],
              os.environ.get("ZH_FONT", "Heiti SC"),
              os.environ.get("EN_FONT", "Helvetica Neue"))
    print(f"\n✅ prep 完成。检查/可改:{p['ass']}\n   然后:burn {p['video']}", file=sys.stderr)


def cmd_burn(args) -> None:
    p = paths_for(str(resolve_video(args.video)))
    ass_arg = getattr(args, "ass", None)
    ass = Path(ass_arg).resolve() if ass_arg else p["ass"]
    trim = args.trim_tail if args.trim_tail is not None else float(os.environ.get("SUBTITLE_TRIM_TAIL", "0"))
    burn(p["video"], ass, p["out"], trim)
    print(f"\n✅ 成品:{p['out']}", file=sys.stderr)


def cmd_run(args) -> None:
    cmd_prep(args)
    cmd_burn(args)


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="subtitle", description="视频 → 中英双语硬字幕")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("video", help="视频文件路径")

    sp = sub.add_parser("prep", help="转写 + 翻译 → .en.srt + .zh.ass")
    add_common(sp)
    sp.add_argument("--src-lang", default=os.environ.get("ASR_LANG", "en"), help="源语言(默认 en)")
    sp.add_argument("--force", action="store_true", help="已有 .zh.ass 也重新生成")
    sp.set_defaults(func=cmd_prep)

    sp = sub.add_parser("burn", help="libass 烧录 → .zh-hardsub.mp4")
    add_common(sp)
    sp.add_argument("ass", nargs="?", help="指定 ass(默认 <video>.zh.ass)")
    sp.add_argument("--trim-tail", type=float, default=None, help="掐掉结尾秒数(防侵权)")
    sp.set_defaults(func=cmd_burn)

    sp = sub.add_parser("run", help="prep + burn 一把过")
    add_common(sp)
    sp.add_argument("--src-lang", default=os.environ.get("ASR_LANG", "en"))
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--trim-tail", type=float, default=None)
    sp.set_defaults(func=cmd_run)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
