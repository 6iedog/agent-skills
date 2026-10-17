#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信读书播客文稿 · 公共库

职责：adb 连接、uiautomator dump（带重试）、LevelDB 拉取与解析、时间轴切片。
所有脚本共用本文件，不绑定任何具体专辑。

环境变量
  WEREAD_SER   adb 序列号，默认 127.0.0.1:5555
  WEREAD_ADB   adb 可执行文件，默认从 PATH / 常见 SDK 路径查找
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

PKG = "com.tencent.weread"
MDS = f"/data/data/{PKG}/app_data_source/mds_db"
WORK = os.environ.get("WEREAD_WORK") or os.path.join(os.path.expanduser("~"), ".weread-podcast")
ENV = dict(os.environ, MSYS_NO_PATHCONV="1")

SIG = '{"synckey"'
KEY_TRACK = re.compile(r"table#trackInfo#TRA_(\d+)_(\d+)(?![0-9])")
KEY_STT = re.compile(r"(?:table#trackInfo#)?local#RemoteTrackSTT#TRA_(\d+)_(\d+)(?![0-9])")
KEY_ALBUM = re.compile(r"table#albumInfo#(\d+)(?![0-9])")


# ---------------------------------------------------------------- adb
def find_adb():
    p = os.environ.get("WEREAD_ADB")
    if p and os.path.exists(p):
        return p
    for cand in (
        r"C:\Develop\AndroidSDK\platform-tools\adb.exe",
        r"C:\Android\platform-tools\adb.exe",
        os.path.expanduser("~/AppData/Local/Android/Sdk/platform-tools/adb.exe"),
        "/usr/local/bin/adb", "/opt/homebrew/bin/adb", "/usr/bin/adb",
    ):
        if os.path.exists(cand):
            return cand
    return "adb"


ADB = find_adb()
SER = os.environ.get("WEREAD_SER", "127.0.0.1:5555")


def shp(args, timeout=120):
    """执行 adb 命令，返回 stdout+stderr"""
    cmd = [ADB]
    if SER:
        cmd += ["-s", SER]
    try:
        p = subprocess.run(cmd + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=ENV)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return f"ERR {e}"


def connect():
    shp(["start-server"])
    if SER and ":" in SER:
        shp(["connect", SER])
    time.sleep(1)
    out = shp(["devices"])
    if "\tdevice" not in out:
        raise SystemExit(f"没有可用设备。adb devices 输出：\n{out}")


def tap(x, y, wait=0.0):
    shp(["shell", f"input tap {x} {y}"])
    if wait:
        time.sleep(wait)


def swipe(x1, y1, x2, y2, ms=340):
    shp(["shell", f"input swipe {x1} {y1} {x2} {y2} {ms}"])


def screencap(name="cur"):
    """截图并转成 RGB 裸数据，返回 bytes（需要 ffmpeg）"""
    png = os.path.join(WORK, name + ".png")
    shp(["shell", "screencap -p /sdcard/_s.png"])
    shp(["pull", "/sdcard/_s.png", png])
    raw = png + ".raw"
    ff = os.environ.get("WEREAD_FFMPEG") or r"C:\Develop\ffmpeg\bin\ffmpeg.exe"
    if not os.path.exists(ff):
        ff = "ffmpeg"
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", png,
                    "-f", "rawvideo", "-pix_fmt", "rgb24", raw], check=True)
    return open(raw, "rb").read()


# ---------------------------------------------------------------- UI 状态
def rdump(tries=8):
    """dump 界面；播放器有动画时会报 could not get idle state 并返回旧文件，必须重试"""
    for _ in range(tries):
        out = shp(["shell", "rm -f /sdcard/_u.xml; uiautomator dump /sdcard/_u.xml"])
        if "ERROR" not in out:
            return True
        time.sleep(1.0)
    return False


def nodes():
    rdump()
    local = os.path.join(WORK, "_u.xml")
    shp(["pull", "/sdcard/_u.xml", local])
    try:
        xml = open(local, encoding="utf-8", errors="replace").read()
    except Exception:
        return []
    out = []
    for m in re.finditer(r"<node\s([^>]*?)/?>", xml):
        s = m.group(1)

        def g(k):
            mm = re.search(k + r'="([^"]*)"', s)
            return mm.group(1) if mm else ""

        out.append((g("bounds"), g("resource-id"), g("text"), g("content-desc")))
    return out


def state():
    """(在播放页, 在AI文稿页)"""
    ids = [n[1] for n in nodes()]
    return (any("PlayerToolBar" in i for i in ids),
            any("album_stt_recycler_view_id" in i for i in ids))


def cur_title():
    """播放页当前集标题（在 content-desc 里）"""
    for b, r, t, d in nodes():
        if b == "[84,350][1516,392]" and (t or d):
            return (t or d)
    return ""


def is_playing():
    for b, r, t, d in nodes():
        if "PlayerToolBarPlay" in r:
            return (t or d) == "暂停"
    return False


def pause():
    """暂停播放。AI 文稿页会跟随播放自动滚动，复制/确认前必须暂停"""
    for _ in range(4):
        if not is_playing():
            return True
        shp(["shell", "input tap 800 664"])
        time.sleep(1.8)
    return not is_playing()


# ---------------------------------------------------------------- LevelDB
def db_dirs():
    """设备上的 mds_db 用户目录（通常只有一个，内容为 main/）"""
    out = shp(["shell", f"su -c 'ls {MDS}'"])
    dirs = []
    for line in out.splitlines():
        d = line.strip()
        if not d or d == "common" or not re.fullmatch(r"\d+", d):
            continue
        chk = shp(["shell", f"su -c 'ls {MDS}/{d}'"])
        if "main" in chk:
            dirs.append(f"{MDS}/{d}")
    return dirs


def pull_db(tag="snap"):
    """把设备缓存拉到 WORK/ldb_<tag>/main，返回本地目录（可能多个，返回列表）"""
    os.makedirs(WORK, exist_ok=True)
    out = []
    for i, d in enumerate(db_dirs()):
        t = "snap" if not tag else f"{tag}{'' if i == 0 else i}"
        tar_local = os.path.join(WORK, f"m_{t}.tar")
        shp(["shell", f"su -c 'cd {d} && tar cf /sdcard/m_{t}.tar main 2>/dev/null'"])
        shp(["pull", f"/sdcard/m_{t}.tar", tar_local])
        dest = os.path.join(WORK, f"ldb_{t}")
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest, exist_ok=True)
        if os.path.exists(tar_local) and os.path.getsize(tar_local) > 1000:
            try:
                with tarfile.open(tar_local) as tf:
                    tf.extractall(dest)
            except Exception:
                pass
        main = os.path.join(dest, "main")
        if os.path.isdir(main) and os.listdir(main):
            out.append(main)
    return out


def snapshots():
    """WORK 下所有已拉取的快照目录（含 ldb_*）"""
    res = []
    if not os.path.isdir(WORK):
        return res
    for name in sorted(os.listdir(WORK)):
        if not name.startswith("ldb"):
            continue
        p = os.path.join(WORK, name)
        if os.path.isdir(os.path.join(p, "main")):
            res.append(os.path.join(p, "main"))
        elif os.path.isdir(p):
            res.append(p)
    return res


def extract_json_at(text, start):
    """从 text[start] 的 '{' 起做括号配对，返回 (json_str, end)"""
    if start < 0 or start >= len(text) or text[start] != "{":
        return None, start
    depth, i, in_str, esc = 0, start, False, False
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1], i + 1
        i += 1
    return None, start


def iter_texts(dirs=None):
    """遍历快照里每个文件的解码文本"""
    for d in (dirs or snapshots()):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not (f.endswith(".ldb") or f.endswith(".log")):
                continue
            yield f, open(os.path.join(d, f), "rb").read().decode("utf-8", "replace")


# ---------------------------------------------------------------- 解析
def norm_pos(pi):
    out = []
    for x in pi or []:
        b = x.get("pos_begin", 0)
        e = x.get("pos_end", 0)
        if e <= b:
            continue
        out.append({"ms_begin": x.get("ms_begin", 0), "ms_end": x.get("ms_end", 0),
                    "pos_begin": b, "pos_end": e})
    out.sort(key=lambda z: z["ms_begin"])
    return out


def load_albums(dirs=None):
    """{albumId: {name, trackCount, isPodcast}}"""
    res = {}
    for f, txt in iter_texts(dirs):
        for m in KEY_ALBUM.finditer(txt):
            j = txt.find("{", m.end())
            js, _ = extract_json_at(txt, j)
            if not js:
                continue
            try:
                o = json.loads(js)
            except Exception:
                continue
            aid = str(o.get("albumId") or m.group(1))
            if not o.get("name"):
                continue
            res[aid] = {"albumId": aid, "name": o["name"],
                        "trackCount": o.get("trackCount"),
                        "isPodcast": o.get("isPodcast")}
    return res


def load_tracks(album, dirs=None):
    """[{uid, idx, title, duration, trackId}] 按 idx 排序"""
    got = {}
    for f, txt in iter_texts(dirs):
        for m in KEY_TRACK.finditer(txt):
            if m.group(1) != str(album):
                continue
            j = txt.find("{", m.end())
            js, _ = extract_json_at(txt, j)
            if not js:
                continue
            try:
                o = json.loads(js)
            except Exception:
                continue
            if not o.get("title"):
                continue
            uid = o.get("trackUid") or int(m.group(2))
            got[str(uid)] = {
                "uid": int(uid),
                "idx": o.get("trackIdx"),
                "title": o["title"],
                "duration": o.get("duration") or 0,
                "trackId": o.get("trackId") or f"TRA_{album}_{uid}",
            }
    rows = [v for v in got.values() if v["idx"] is not None]
    rows.sort(key=lambda r: r["idx"])
    return rows


def load_stt(album, tracks, dirs=None):
    """{uid: {text, posInfo, match}}
    先按 key 精确取；剩下的记录（key 被 LevelDB 前缀压缩）按
    「末尾毫秒 ≈ 曲目时长」+「字数/秒合理」兜底匹配，并标记 match='loose'。
    """
    by_key, loose = {}, []
    for f, txt in iter_texts(dirs):
        for m in KEY_STT.finditer(txt):
            if m.group(1) != str(album):
                continue
            j = txt.find("{", m.end())
            js, _ = extract_json_at(txt, j)
            if not js:
                continue
            try:
                o = json.loads(js)
            except Exception:
                continue
            t = o.get("text") or ""
            if not t:
                continue
            uid = m.group(2)
            if len(t) > len(by_key.get(uid, {}).get("text", "")):
                by_key[uid] = {"text": t, "posInfo": norm_pos(o.get("posInfo")), "match": "key"}
        st = 0
        while True:
            j = txt.find(SIG, st)
            if j < 0:
                break
            st = j + len(SIG)
            js, _ = extract_json_at(txt, j)
            if not js:
                continue
            try:
                o = json.loads(js)
            except Exception:
                continue
            t = o.get("text") or ""
            pi = norm_pos(o.get("posInfo"))
            if t and pi:
                loose.append((t, pi))

    res = dict(by_key)
    for tr in tracks:
        uid = str(tr["uid"])
        if uid in res:
            continue
        dur = tr["duration"] or 0
        if not dur:
            continue
        best, bd = None, 1e9
        for t, pi in loose:
            d = abs(pi[-1]["ms_end"] - dur)
            if d > 2500 or d >= bd:
                continue
            cps = len(t) / max(dur / 1000.0, 1e-6)
            if not (2.0 <= cps <= 9.0):
                continue
            bd, best = d, (t, pi)
        if best:
            res[uid] = {"text": best[0], "posInfo": best[1], "match": "loose"}
    return res


# ---------------------------------------------------------------- 时间轴
def parse_time(s):
    """90 / 90s / 1:30 / 01:30 / 1:02:03 -> 毫秒"""
    if s is None or s == "":
        return None
    s = str(s).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s) * 1000)
    if re.fullmatch(r"\d+(\.\d+)?s", s):
        return int(float(s[:-1]) * 1000)
    parts = [float(x) for x in s.split(":")]
    if len(parts) == 2:
        return int((parts[0] * 60 + parts[1]) * 1000)
    if len(parts) == 3:
        return int((parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000)
    raise ValueError(f"看不懂的时间: {s}")


def fmt_time(ms):
    s = int((ms or 0) // 1000)
    return f"{s // 60:02d}:{s % 60:02d}" if s < 3600 else \
        f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def slice_ep(ep, t0=None, t1=None):
    """按毫秒区间切句，返回 [(ms_begin, sentence)]"""
    pi = ep.get("posInfo") or []
    txt = ep.get("text") or ""
    if not pi:
        return [(0, txt)] if txt else []
    total = pi[-1]["ms_end"] or ep.get("duration") or 1
    t0 = 0 if t0 is None else t0
    t1 = total if t1 is None else min(t1, total)
    out = []
    for x in pi:
        if x["ms_end"] <= t0 or x["ms_begin"] >= t1:
            continue
        seg = txt[x["pos_begin"]:x["pos_end"]].strip()
        if seg:
            out.append((x["ms_begin"], seg))
    return out


def safe_name(s, n=48):
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:n] or "untitled"


def ensure_work():
    os.makedirs(WORK, exist_ok=True)
    return WORK
