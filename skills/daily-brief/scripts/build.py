#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
早报构建器：Markdown 早报 -> 单文件美观 HTML（每条新闻一段独立语音，串成播放列表）

用法:
    python build.py <早报.md> [--voice zh-CN-XiaoyiNeural] [--rate +8%] [--no-embed] [--no-audio]

产出:
    <同名>.html              —— 网页；音频**默认以 base64 内嵌**，单文件打开就能听
                                （内嵌是为了在手机/小程序里直接打开也有效，不依赖同目录文件；
                                 加 --no-embed 才改回外链到 <同名>.audio/NN.mp3）
    <同名>.audio/NN.mp3      —— 每条新闻一段语音（缓存，重建时复用，切音色前先删）
    <同名>.mp3               —— 全篇合集（分段拼接），方便整个带走听

特性:
    每张卡片一个播放按钮；顶部是播放列表控制器；播完一条自动续播下一条；支持倍速与逐节播放。
    已存在的分段 mp3 会直接复用，不会重复合成（改音色时需先删掉旧 mp3）。

依赖: edge-tts（仅合成时需要；缺失或失败会自动降级为无音频网页）
"""

import argparse
import base64
import html as html_mod
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

DEFAULT_VOICE = "zh-CN-XiaoyiNeural"
DEFAULT_RATE = "+8%"

ICON_PLAY = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>'


# ---------------------------------------------------------------- 文本清洗


def md_to_speech(md: str) -> str:
    """把一段 markdown 洗成适合朗读的纯文本。"""
    text = md
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1", text)
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*_=]{3,}\s*$", "", text, flags=re.M)
    text = re.sub(r"[*_~]{1,3}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    out = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"https?://\S+", line):
            continue
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- 语音合成


def synth_batch(jobs, voice: str, rate: str, concurrency: int = 4):
    """并发合成多段。jobs: [(idx, text, out_path)] -> 返回失败的 idx 集合。

    单进程内并发（复用一个事件循环），比逐段起子进程快得多。
    若环境里没有 edge_tts 模块则返回 None，由调用方回退到 CLI 方式。
    """
    try:
        import asyncio
        import edge_tts
    except ImportError:
        return None

    failed = set()

    async def runner():
        sem = asyncio.Semaphore(concurrency)

        async def one(idx, text, out):
            for attempt in range(3):
                try:
                    async with sem:
                        c = edge_tts.Communicate(text, voice, rate=rate)
                        await c.save(str(out))
                    if out.exists() and out.stat().st_size > 1024:
                        print("  [%02d] 已合成 %s" % (idx, out.name), flush=True)
                        return
                except Exception as e:
                    print("  [%02d] 第 %d 次失败: %s" % (idx, attempt + 1, str(e)[:120]), flush=True)
                await asyncio.sleep(2 + attempt * 2)
            failed.add(idx)
            try:
                if out.exists() and out.stat().st_size <= 1024:
                    out.unlink()
            except Exception:
                pass

        await asyncio.gather(*[one(i, t, o) for i, t, o in jobs])

    asyncio.run(runner())
    return failed


def synth(text: str, out_mp3: Path, voice: str, rate: str, tries: int = 3) -> bool:
    """调用 edge-tts 合成单段 mp3；偶发网络抖动会自动重试。"""
    import time

    last_err = ""
    for attempt in range(tries):
        tmp = None
        try:
            out_mp3.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp()) / "speech.txt"
            tmp.write_text(text, encoding="utf-8")
            cmd = [
                sys.executable, "-m", "edge_tts",
                "--voice", voice, "--rate", rate,
                "--file", str(tmp), "--write-media", str(out_mp3),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if r.returncode == 0 and out_mp3.exists() and out_mp3.stat().st_size > 1024:
                return True
            last_err = (r.stderr or r.stdout or "")[:200]
        except FileNotFoundError:
            print("[warn] 找不到 edge-tts，跳过语音。安装: pip install edge-tts", file=sys.stderr)
            return False
        except Exception as e:
            last_err = str(e)
        finally:
            if tmp and tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
        if attempt < tries - 1:
            time.sleep(2 + attempt * 2)

    # 失败就清掉残骸（0 字节文件会让下次误判为已存在）
    try:
        if out_mp3.exists() and out_mp3.stat().st_size <= 1024:
            out_mp3.unlink()
    except Exception:
        pass
    print("[warn] 合成失败（已重试 %d 次）: %s" % (tries, last_err), file=sys.stderr)
    return False


# MP3 首帧估算时长（CBR 足够准；浏览器加载后会用真实 duration 覆盖）
_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]


def mp3_seconds(path: Path) -> float:
    try:
        data = path.read_bytes()
    except Exception:
        return 0.0
    i = 0
    if data[:3] == b"ID3":
        i = 10 + (((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F))
    n = len(data)
    while i < n - 4:
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            ver = (data[i + 1] >> 3) & 0x03
            br = (data[i + 2] >> 4) & 0x0F
            table = _V1L3 if ver == 3 else (_V2L3 if ver in (0, 2) else None)
            if table and 1 <= br <= 14:
                return len(data) * 8 / (table[br] * 1000.0)
        i += 1
    return 0.0


def strip_id3(data: bytes) -> bytes:
    if data[:3] != b"ID3":
        return data
    size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
    return data[10 + size:]


def fmt_time(sec: float) -> str:
    sec = int(sec or 0)
    return "%d:%02d" % (sec // 60, sec % 60)


# ---------------------------------------------------------------- Markdown 解析


INLINE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*")


def inline(s: str) -> str:
    s = html_mod.escape(s)
    s = INLINE_LINK.sub(lambda m: '<a href="%s" target="_blank" rel="noopener">%s</a>' % (m.group(2), m.group(1)), s)
    s = BOLD.sub(r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def extract_links(s: str):
    return [(m.group(1), m.group(2)) for m in INLINE_LINK.finditer(s)]


def domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1).replace("www.", "") if m else ""


def _blocks(text: str):
    out = []
    for b in re.split(r"\n\s*\n", text):
        b = b.strip()
        if not b or re.fullmatch(r"[-*_=~\s]+", b):
            continue
        out.append(b)
    return out


LINK_LINE = re.compile(r"^\[[^\]]+\]\(https?://[^)]+\)")
INSIGHT_RE = re.compile(r"^\**\s*为什么值得看\s*\**\s*[：:]?\s*")


def parse(md: str):
    """解析早报 md -> 结构化数据。兼容 ### 标题 与 **标题** 两种条目写法。"""
    doc = {"title": "早报", "date": "", "date_line": "", "lede": "", "sections": [], "quiet": "", "thread": ""}
    parts = re.split(r"(?m)^##\s+", md)
    head = parts[0]

    m = re.search(r"(?m)^#\s+(.*)$", head)
    if m:
        doc["title"] = m.group(1).strip()
    dm = re.search(r"(\d{4}-\d{2}-\d{2})", doc["title"])
    if dm:
        doc["date"] = dm.group(1)
    doc["date_line"] = re.sub(r"^早报\s*·\s*", "", doc["title"]).strip() or doc["title"]

    for b in _blocks(re.sub(r"(?m)^#\s+.*$", "", head)):
        doc["lede"] = b
        break

    for p in parts[1:]:
        ls = p.split("\n")
        name = ls[0].strip()
        body = "\n".join(ls[1:])

        if "安静" in name or "没东西" in name:
            doc["quiet"] = " ".join(_blocks(body)) or name
            continue
        if "主线" in name:
            doc["thread"] = " ".join(_blocks(body))
            continue

        blocks = _blocks(body)
        use_h3 = any(re.match(r"^###\s+", b) for b in blocks)

        items = []
        for b in blocks:
            lines = []
            for l in b.split("\n"):
                l = re.sub(r"^\s*>\s?", "", l).strip()
                if not l or re.fullmatch(r"[-*_]{3,}", l):
                    continue
                lines.append(l)
            if not lines:
                continue

            raw0 = lines[0]
            if use_h3:
                is_title = bool(re.match(r"^#{1,6}\s+", raw0))
            else:
                h0 = re.sub(r"^[-*]\s+", "", raw0).strip()
                is_title = h0.startswith("**") and not INSIGHT_RE.match(h0)
            title_txt = re.sub(r"^#{1,6}\s+", "", raw0).strip() if is_title else ""

            if is_title:
                items.append({"title": title_txt, "links": extract_links(title_txt), "body": [], "insight": ""})
                rest = lines[1:]
            else:
                if not items:
                    items.append({"title": "", "links": [], "body": [], "insight": ""})
                rest = lines

            para = []
            for l in rest:
                mi = INSIGHT_RE.match(l)
                if mi:
                    if para:
                        items[-1]["body"].append(" ".join(para))
                        para = []
                    items[-1]["insight"] = (items[-1]["insight"] + " " + l[mi.end():].strip()).strip()
                elif LINK_LINE.match(l):
                    items[-1]["links"].extend(extract_links(l))
                else:
                    para.append(l)
            if para:
                items[-1]["body"].append(" ".join(para))

        if items:
            doc["sections"].append({"name": name, "items": items})

    return doc


def flatten(doc: dict):
    """给每条可朗读的条目编全局序号 -> [(idx, section_name, item)]。"""
    out, n = [], 0
    for sec in doc["sections"]:
        for it in sec["items"]:
            if not it["title"] and not it["insight"]:
                continue  # 脚注卡片不朗读
            out.append((n, sec["name"], it))
            n += 1
    return out


def item_speech(sec_name: str, it: dict) -> str:
    chunks = []
    if it["title"]:
        chunks.append(md_to_speech(it["title"]).strip() + "。")
    for b in it["body"]:
        t = md_to_speech(b).strip()
        if t:
            chunks.append(t)
    if it["insight"]:
        t = md_to_speech(it["insight"]).strip()
        if t:
            chunks.append("铁蛋插一句。" + t)
    return "\n".join(chunks)


# ---------------------------------------------------------------- 样式

CSS = """
:root{
  --paper:#faf8f4; --card:#ffffff; --ink:#1c1b19; --ink-2:#4a4744; --ink-3:#8a857e;
  --line:#e8e3da; --accent:#b4531f; --accent-soft:#fdf3ec; --chip:#f2ede4;
  --shadow:0 1px 2px rgba(28,27,25,.04),0 8px 24px -12px rgba(28,27,25,.12);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--paper); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif;
  font-size:16px; line-height:1.75; -webkit-font-smoothing:antialiased;
  background-image:radial-gradient(circle at 1px 1px, rgba(28,27,25,.045) 1px, transparent 0);
  background-size:22px 22px;
}
.wrap{max-width:760px;margin:0 auto;padding:56px 24px 96px}
.kicker{font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--accent);font-weight:700;margin-bottom:14px}
h1.title{font-family:Georgia,"Songti SC","Noto Serif SC",serif;font-size:40px;line-height:1.2;margin:0 0 8px;font-weight:700;letter-spacing:-.01em}
.dateline{color:var(--ink-3);font-size:14px;margin-bottom:28px}
.lede{font-family:Georgia,"Songti SC","Noto Serif SC",serif;font-size:19px;line-height:1.7;color:var(--ink-2);
  border-left:3px solid var(--accent);padding:2px 0 2px 16px;margin:0 0 32px}

/* ---- 播放列表控制器 ---- */
.player{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 16px;
  box-shadow:var(--shadow);margin:0 0 26px;position:sticky;top:10px;z-index:30;backdrop-filter:blur(6px)}
.prow{display:flex;align-items:center;gap:12px}
.playbtn{flex:none;width:46px;height:46px;border-radius:50%;border:0;cursor:pointer;background:var(--accent);color:#fff;
  display:grid;place-items:center;box-shadow:0 4px 12px -2px rgba(180,83,31,.45);transition:transform .15s ease}
.playbtn:hover{transform:scale(1.05)} .playbtn:active{transform:scale(.97)}
.playbtn svg{width:19px;height:19px;fill:currentColor}
.pmeta{flex:1;min-width:0}
.track{font-size:13.5px;color:var(--ink);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:5px}
.track .no{color:var(--accent);font-variant-numeric:tabular-nums;margin-right:6px}
.track.idle{color:var(--ink-3);font-weight:400}
.bar{flex:1;height:5px;border-radius:99px;background:var(--line);cursor:pointer;position:relative;overflow:hidden}
.bar>i{position:absolute;left:0;top:0;bottom:0;width:0%;background:var(--accent);border-radius:99px;display:block}
.time{font-size:11.5px;color:var(--ink-3);font-variant-numeric:tabular-nums;flex:none}
.mini{flex:none;border:1px solid var(--line);background:var(--chip);color:var(--ink-2);border-radius:8px;
  width:30px;height:30px;display:grid;place-items:center;cursor:pointer}
.mini svg{width:14px;height:14px;fill:currentColor}
.mini:hover{border-color:var(--accent);color:var(--accent)}
.speed{flex:none;border:1px solid var(--line);background:var(--chip);color:var(--ink-2);font-size:12px;
  border-radius:99px;padding:5px 10px;cursor:pointer;font-weight:600;height:30px}
.speed:hover{border-color:var(--accent);color:var(--accent)}
.speed.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.wave{display:flex;align-items:flex-end;gap:2px;height:20px;flex:none}
.wave i{width:3px;border-radius:2px;background:var(--accent);opacity:.3;height:30%;display:block}
.player.playing .wave i{animation:wb 1s ease-in-out infinite}
.wave i:nth-child(2){animation-delay:.15s}.wave i:nth-child(3){animation-delay:.3s}
.wave i:nth-child(4){animation-delay:.45s}.wave i:nth-child(5){animation-delay:.6s}
@keyframes wb{0%,100%{height:25%}50%{height:100%}}
.player-foot{display:flex;align-items:center;gap:10px;margin-top:9px;padding-top:9px;border-top:1px dashed var(--line)}
.hint{font-size:11.5px;color:var(--ink-3)}

/* ---- nav chips ---- */
.nav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 34px}
.chip{display:inline-flex;align-items:center;gap:7px;background:var(--chip);border:1px solid var(--line);
  border-radius:99px;padding:6px 13px;font-size:13px;color:var(--ink-2);text-decoration:none;transition:all .15s}
.chip:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
.chip span{font-size:11px;font-weight:700;color:var(--ink-3);font-variant-numeric:tabular-nums}
.chip:hover span{color:var(--accent)}

/* ---- sections ---- */
section{margin:0 0 38px;scroll-margin-top:120px}
.sec-head{display:flex;align-items:center;gap:12px;margin:0 0 16px;padding-bottom:10px;border-bottom:1px solid var(--line)}
.sec-num{font-size:12px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums;letter-spacing:.08em}
.sec-name{font-size:13px;font-weight:700;letter-spacing:.16em;color:var(--ink-2);text-transform:uppercase}
.secplay{margin-left:auto;display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--chip);
  color:var(--ink-3);font-size:11.5px;border-radius:99px;padding:4px 11px;cursor:pointer;font-weight:600}
.secplay svg{width:11px;height:11px;fill:currentColor}
.secplay:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}

.item{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 22px;margin-bottom:14px;
  box-shadow:var(--shadow);transition:border-color .2s,box-shadow .2s;scroll-margin-top:130px}
.item.playing{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft),var(--shadow)}
.item.note{background:transparent;border-style:dashed;box-shadow:none;padding:11px 16px;color:var(--ink-3);font-size:13px}
.item.note p{color:var(--ink-3);font-size:13px;margin:0}
.item-head{display:flex;align-items:flex-start;gap:13px}
.itemplay{flex:none;width:36px;height:36px;border-radius:50%;border:1px solid var(--line);background:var(--chip);
  color:var(--ink-2);display:grid;place-items:center;cursor:pointer;transition:all .15s;margin-top:1px}
.itemplay svg{width:15px;height:15px;fill:currentColor;margin-left:1px}
.itemplay:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
.item.playing .itemplay{background:var(--accent);color:#fff;border-color:var(--accent)}
.item.playing .itemplay svg{margin-left:0}
.ttl{flex:1;min-width:0}
.item h3{margin:0 0 10px;font-size:18px;line-height:1.5;font-weight:700}
.dur{flex:none;font-size:11.5px;color:var(--ink-3);font-variant-numeric:tabular-nums;padding-top:10px}
.item p{margin:0 0 10px;color:var(--ink-2);font-size:15.5px}
.item p:last-child{margin-bottom:0}
.src{font-size:12px;color:var(--ink-3);margin-top:10px}
.src a{color:var(--ink-3);text-decoration:none;border-bottom:1px dotted var(--line)}
.src a:hover{color:var(--accent)}
.insight{background:var(--accent-soft);border-radius:10px;padding:12px 14px;margin-top:14px;font-size:14.5px;color:#7c3a12;line-height:1.7}
.insight b,.insight strong{color:var(--accent);font-weight:700;margin-right:2px}

/* ---- tail ---- */
.quiet{background:transparent;border:1px dashed var(--line);border-radius:12px;padding:14px 18px;color:var(--ink-3);font-size:14px;margin:0 0 30px}
.thread{background:linear-gradient(135deg,#1c1b19,#3a352f);color:#f5f1ea;border-radius:16px;padding:26px 28px;margin:0 0 30px;box-shadow:var(--shadow)}
.thread .cap{font-size:11px;letter-spacing:.2em;color:#c8a98c;font-weight:700;margin-bottom:10px}
.thread p{margin:0;font-size:16.5px;line-height:1.8}
.thread strong{color:#fff}
footer{border-top:1px solid var(--line);padding-top:20px;color:var(--ink-3);font-size:12.5px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
@media(max-width:640px){
  .wrap{padding:36px 16px 72px}
  h1.title{font-size:30px}
  .player{position:static}
  .thread{padding:20px}
  .item{padding:16px 17px}
  .dur{display:none}
}
@media print{body{background:#fff}.player,.itemplay,.secplay{display:none}.item{break-inside:avoid}}
"""

JS = """
(function(){
  var cards=[].slice.call(document.querySelectorAll('.item[data-idx]'));
  var btn=document.getElementById('playbtn'),track=document.getElementById('track'),
      fill=document.getElementById('fill'),bar=document.getElementById('bar'),
      curT=document.getElementById('cur'),durT=document.getElementById('dur'),
      sp=document.getElementById('speed'),autoBtn=document.getElementById('auto'),
      prev=document.getElementById('prev'),next=document.getElementById('next'),
      player=document.getElementById('player');
  var A={},order=[];
  cards.forEach(function(c){
    var a=c.querySelector('audio'); if(!a) return;
    var i=parseInt(c.getAttribute('data-idx'),10);
    A[i]={el:c,au:a,title:c.getAttribute('data-title')||''};
    order.push(i);
  });
  order.sort(function(x,y){return x-y;});
  if(!order.length) return;

  var curIdx=-1, auto=true, stopAt=-1;
  var rates=[1,1.25,1.5,2], ri=0, rate=1;
  var IP='<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>',
      IPa='<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>';
  function fmt(s){ if(!isFinite(s)) return '0:00'; s=Math.floor(s); var m=Math.floor(s/60),x=s%60; return m+':'+(x<10?'0':'')+x; }
  function mark(i){ cards.forEach(function(c){ c.classList.toggle('playing', parseInt(c.getAttribute('data-idx'),10)===i); }); }
  function label(){
    if(curIdx<0){ track.className='track idle'; track.textContent='点任意卡片上的播放键，或从这里整份连播'; return; }
    track.className='track';
    track.innerHTML='<span class="no">'+(order.indexOf(curIdx)+1)+'/'+order.length+'</span>'+A[curIdx].title;
  }
  function prog(){
    var a=curIdx<0?null:A[curIdx].au;
    if(!a||!a.duration){ fill.style.width='0%'; curT.textContent='0:00'; durT.textContent='--:--'; return; }
    fill.style.width=(a.currentTime/a.duration*100)+'%';
    curT.textContent=fmt(a.currentTime); durT.textContent=fmt(a.duration);
  }
  function stopOthers(except){ order.forEach(function(i){ if(i!==except){ var a=A[i].au; if(!a.paused) a.pause(); } }); }
  function play(i){
    if(!(i in A)) return;
    stopOthers(i); curIdx=i;
    var a=A[i].au; a.playbackRate=rate;
    var p=a.play(); if(p&&p.catch) p.catch(function(){});
    mark(i); label(); player.classList.add('playing'); btn.innerHTML=IPa;
    var r=A[i].el.getBoundingClientRect();
    if(r.top<60||r.top>window.innerHeight-120) A[i].el.scrollIntoView({behavior:'smooth',block:'center'});
  }
  function toggle(i){
    if(curIdx!==i){ play(i); return; }
    if(A[i].au.paused){ A[i].au.play(); } else { A[i].au.pause(); }
  }
  function reset(){
    if(curIdx>=0) mark(-1);
    curIdx=-1; stopAt=-1; player.classList.remove('playing'); btn.innerHTML=IP;
    fill.style.width='0%'; curT.textContent='0:00'; durT.textContent='--:--'; label();
  }
  function step(d){
    var k=order.indexOf(curIdx);
    if(k<0){ stopAt=-1; play(order[0]); return; }
    var n=k+d;
    if(n<0||n>=order.length) return;
    if(d>0 && stopAt>=0 && order[n]>stopAt) return;
    play(order[n]);
  }

  order.forEach(function(i){
    var a=A[i].au;
    a.addEventListener('play',function(){ if(i===curIdx){ btn.innerHTML=IPa; player.classList.add('playing'); } });
    a.addEventListener('pause',function(){ if(i===curIdx){ btn.innerHTML=IP; player.classList.remove('playing'); } });
    a.addEventListener('timeupdate',function(){ if(i===curIdx) prog(); });
    a.addEventListener('loadedmetadata',function(){ if(i===curIdx) prog(); });
    a.addEventListener('ended',function(){
      if(i!==curIdx) return;
      var k=order.indexOf(i);
      var nx=(k>=0&&k<order.length-1)?order[k+1]:-1;
      if(auto && nx>=0 && (stopAt<0 || nx<=stopAt)) play(nx);
      else reset();
    });
  });

  cards.forEach(function(c){
    var b=c.querySelector('.itemplay');
    if(!b) return;
    b.addEventListener('click',function(){ toggle(parseInt(c.getAttribute('data-idx'),10)); });
  });

  [].slice.call(document.querySelectorAll('.secplay')).forEach(function(b){
    b.addEventListener('click',function(){
      stopAt=parseInt(b.getAttribute('data-to'),10);
      play(parseInt(b.getAttribute('data-from'),10));
    });
  });

  btn.addEventListener('click',function(){
    if(curIdx<0){ stopAt=-1; play(order[0]); } else toggle(curIdx);
  });
  prev.addEventListener('click',function(){ step(-1); });
  next.addEventListener('click',function(){ step(1); });
  sp.addEventListener('click',function(){
    ri=(ri+1)%rates.length; rate=rates[ri];
    order.forEach(function(i){ A[i].au.playbackRate=rate; });
    sp.textContent=(rates[ri]===1?'1':String(rates[ri]))+'×';
  });
  autoBtn.addEventListener('click',function(){
    auto=!auto; autoBtn.classList.toggle('on',auto);
    autoBtn.textContent=auto?'连播 开':'连播 关';
  });
  function seek(e){
    if(curIdx<0) return;
    var a=A[curIdx].au; if(!a.duration) return;
    var r=bar.getBoundingClientRect();
    var x=(e.touches?e.touches[0].clientX:e.clientX)-r.left;
    a.currentTime=Math.min(1,Math.max(0,x/r.width))*a.duration;
  }
  bar.addEventListener('click',seek);
  bar.addEventListener('touchmove',seek);
  document.addEventListener('keydown',function(e){
    if(e.code==='Space'&&e.target===document.body){ e.preventDefault(); if(curIdx<0){ stopAt=-1; play(order[0]); } else toggle(curIdx); }
  });
  label();
})();
"""


# ---------------------------------------------------------------- 渲染


def render(doc: dict, audio: dict) -> str:
    """audio: {idx: (src, seconds)}，src 可以是外链路径或 data URI。"""
    e = html_mod.escape
    parts = []

    n_tracks = len(audio)
    total = sum(s for _, s in audio.values())
    head = "语音版 · %d 段" % n_tracks
    if total:
        head += " · 共 %s" % fmt_time(total)

    parts.append(
        '<div class="player" id="player">'
        '<div class="prow">'
        '<button class="playbtn" id="playbtn" aria-label="播放">%s</button>'
        '<div class="pmeta">'
        '<div class="track idle" id="track"></div>'
        '<div class="prow">'
        '<span class="time" id="cur">0:00</span>'
        '<div class="bar" id="bar"><i id="fill"></i></div>'
        '<span class="time" id="dur">--:--</span>'
        '</div></div>'
        '<div class="wave"><i></i><i></i><i></i><i></i><i></i></div>'
        '</div>'
        '<div class="player-foot">'
        '<button class="mini" id="prev" aria-label="上一条"><svg viewBox="0 0 24 24"><path d="M6 5h3v14H6zm11 0v14l-9-7z"/></svg></button>'
        '<button class="mini" id="next" aria-label="下一条"><svg viewBox="0 0 24 24"><path d="M15 5h3v14h-3zM6 5l9 7-9 7z"/></svg></button>'
        '<button class="speed" id="speed">1×</button>'
        '<button class="speed on" id="auto">连播 开</button>'
        '<span class="hint">播完自动接下一条</span>'
        '</div>'
        '</div>' % ICON_PLAY
    )

    parts.append('<div class="kicker">Daily Brief</div>')
    parts.append('<h1 class="title">%s</h1>' % e(doc.get("date_line") or doc["title"]))
    if doc.get("date"):
        parts.append('<div class="dateline">%s · %s</div>' % (e(doc["date"]), e(head)))
    if doc["lede"]:
        parts.append('<div class="lede">%s</div>' % inline(doc["lede"]))

    live = [(i, s) for i, s in enumerate(doc["sections"], 1) if s["items"]]
    if len(live) > 2:
        chips = "".join(
            '<a class="chip" href="#s%d">%s<span>%d</span></a>' % (i, e(s["name"]), len(s["items"]))
            for i, s in sorted(live, key=lambda x: -len(x[1]["items"]))
        )
        parts.append('<nav class="nav">%s</nav>' % chips)

    n = 0
    for si, sec in live:
        rng = []
        for it in sec["items"]:
            if it["title"] or it["insight"]:
                rng.append(n)
                n += 1
        parts.append('<section id="s%d">' % si)
        parts.append('<div class="sec-head"><span class="sec-num">%02d</span><span class="sec-name">%s</span>' % (si, e(sec["name"])))
        if rng:
            parts.append('<button class="secplay" data-from="%d" data-to="%d">%s 本节</button>' % (rng[0], rng[-1], ICON_PLAY))
        parts.append('</div>')

        k = 0
        for it in sec["items"]:
            if not it["title"] and not it["insight"]:
                parts.append('<div class="item note">')
                for b in it["body"]:
                    parts.append('<p>%s</p>' % inline(b))
                parts.append('</div>')
                continue

            idx = rng[k]
            k += 1
            src, secs = audio.get(idx, ("", 0))
            short = re.sub(r"\s+", " ", it["title"] or sec["name"])[:40]

            parts.append('<div class="item" data-idx="%d" data-title="%s">' % (idx, e(short)))
            parts.append('<div class="item-head">')
            if src:
                parts.append('<button class="itemplay" aria-label="播放这条">%s</button>' % ICON_PLAY)
            parts.append('<div class="ttl">')
            if it["title"]:
                parts.append('<h3>%s</h3>' % inline(it["title"]))
            parts.append('</div>')
            if src and secs:
                parts.append('<span class="dur">%s</span>' % fmt_time(secs))
            parts.append('</div>')

            for b in it["body"]:
                parts.append('<p>%s</p>' % inline(b))
            if it["links"]:
                srcs = " · ".join(
                    '<a href="%s" target="_blank" rel="noopener">%s</a>' % (u, e(domain_of(u) or "来源"))
                    for _, u in it["links"][:3]
                )
                parts.append('<div class="src">来源：%s</div>' % srcs)
            if it["insight"]:
                parts.append('<div class="insight"><strong>为什么值得看 ·</strong>%s</div>' % inline(it["insight"]))
            if src:
                parts.append('<audio preload="metadata" src="%s"></audio>' % src)
            parts.append('</div>')

        parts.append('</section>')

    if doc["quiet"]:
        parts.append('<div class="quiet">今天安静的领域：%s</div>' % inline(doc["quiet"]))
    if doc["thread"]:
        parts.append('<div class="thread"><div class="cap">今日主线</div><p>%s</p></div>' % inline(doc["thread"]))

    tail = e(doc.get("date", ""))
    if n_tracks:
        tail += " · 语音 %d 段" % n_tracks
    parts.append('<footer><span>铁蛋 · 晨间情报</span><span>%s</span></footer>' % tail)

    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title><style>%s</style></head><body><div class="wrap">%s</div>'
        '<script>%s</script></body></html>'
    ) % (e(doc.get("date_line") or "早报"), CSS, "\n".join(parts), JS)


# ---------------------------------------------------------------- 主流程


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--rate", default=DEFAULT_RATE)
    ap.add_argument("--embed", dest="embed", action="store_true", default=True,
                    help="把音频以 base64 内嵌进 HTML（默认开：单文件即可播放，手机/小程序里也有效）")
    ap.add_argument("--no-embed", dest="embed", action="store_false",
                    help="音频改为外链到同目录 <同名>.audio/NN.mp3（体积小，但换环境会丢音频）")
    ap.add_argument("--no-audio", action="store_true")
    args = ap.parse_args()

    md_path = Path(args.md).resolve()
    if not md_path.exists():
        print("找不到文件: %s" % md_path, file=sys.stderr)
        sys.exit(1)
    doc = parse(md_path.read_text(encoding="utf-8"))

    items = flatten(doc)
    print("[..] 共 %d 条待处理" % len(items))

    audio_dir = md_path.parent / (md_path.stem + ".audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    rel_dir = quote(md_path.stem + ".audio", safe="")
    audio, concat_parts = {}, {}

    if not args.no_audio and items:
        jobs = []
        for idx, sec_name, it in items:
            seg = audio_dir / ("%02d.mp3" % idx)
            if seg.exists() and seg.stat().st_size > 1024:
                continue
            jobs.append((idx, item_speech(sec_name, it), seg))

        if jobs:
            print("[..] 待合成 %d 段（并发 4）" % len(jobs), flush=True)
            bad = synth_batch(jobs, args.voice, args.rate)
            if bad is None:  # 没有 edge_tts 模块，退回逐段 CLI
                for idx, text, seg in jobs:
                    synth(text, seg, args.voice, args.rate)

        for idx, sec_name, it in items:
            seg = audio_dir / ("%02d.mp3" % idx)
            if seg.exists() and seg.stat().st_size > 1024:
                secs = mp3_seconds(seg)
                if args.embed:
                    src = "data:audio/mpeg;base64," + base64.b64encode(seg.read_bytes()).decode("ascii")
                else:
                    src = "%s/%02d.mp3" % (rel_dir, idx)
                audio[idx] = (src, secs)
                concat_parts[idx] = seg.read_bytes()
                print("  [%02d] %s · %s" % (idx, fmt_time(secs), re.sub(r"\s+", " ", it["title"])[:32]), flush=True)
            else:
                print("  [%02d] 无语音" % idx, file=sys.stderr, flush=True)

    if concat_parts:
        whole = md_path.with_suffix(".mp3")
        try:
            whole.write_bytes(b"".join(strip_id3(concat_parts[k]) for k in sorted(concat_parts)))
            print("[ok] 合集 %s（%.2f MB）" % (whole.name, whole.stat().st_size / 1024 / 1024))
        except Exception as ex:
            print("[warn] 合集写入失败: %s" % ex, file=sys.stderr)

    out = md_path.with_suffix(".html")
    out.write_text(render(doc, audio), encoding="utf-8")
    total = sum(s for _, s in audio.values())
    size_mb = out.stat().st_size / 1024 / 1024
    mode = "音频已内嵌" if args.embed else "音频外链"
    print("[ok] %s（%.2f MB · %s · %d 段语音 · 共 %s）" % (out.name, size_mb, mode, len(audio), fmt_time(total)))
    if args.embed and size_mb > 14:
        print("[warn] 单文件偏大（%.1f MB），手机首次打开会慢——文案再精简些就能瘦下来。" % size_mb, file=sys.stderr)
    print(str(out))


if __name__ == "__main__":
    main()
