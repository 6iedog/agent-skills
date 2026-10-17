#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""枚举专辑 / 曲目 / 文稿，生成索引 index_<albumId>.json

用法
  python scan.py --list                     # 列出缓存里出现过的所有专辑
  python scan.py --album 3110116986         # 用已有快照建索引
  python scan.py --album 3110116986 --pull  # 先从设备拉一份最新缓存再建索引
  python scan.py --album 3110116986 --show-missing   # 只列出还没有文稿的集
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wb


def build(album, dirs):
    albums = wb.load_albums(dirs)
    info = albums.get(str(album), {"albumId": str(album), "name": str(album), "trackCount": None})
    tracks = wb.load_tracks(album, dirs)
    if not tracks:
        raise SystemExit(f"专辑 {album} 在缓存里没有曲目记录，确认 albumId 是否正确")
    stt = wb.load_stt(album, tracks, dirs)

    eps = []
    for t in tracks:
        s = stt.get(str(t["uid"])) or {}
        eps.append({
            "idx": t["idx"], "uid": t["uid"], "trackId": t["trackId"],
            "title": t["title"], "duration": t["duration"],
            "text": s.get("text", ""), "posInfo": s.get("posInfo", []),
            "match": s.get("match", ""),
        })
    return {
        "album": info,
        "generated": int(time.time()),
        "eps": eps,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--album", help="专辑 albumId")
    ap.add_argument("--list", action="store_true", help="列出缓存里的专辑")
    ap.add_argument("--pull", action="store_true", help="先从设备拉最新缓存")
    ap.add_argument("--show-missing", action="store_true", help="列出缺文稿的集")
    ap.add_argument("--dirs", nargs="*", help="直接指定本地快照目录（跳过拉取）")
    ap.add_argument("--out", help="索引输出路径")
    a = ap.parse_args()

    wb.ensure_work()
    if a.pull:
        wb.connect()
        print("拉取缓存…")
        for d in wb.pull_db("snap"):
            print("  ", d)
    dirs = a.dirs or wb.snapshots()
    if not dirs:
        raise SystemExit(f"{wb.WORK} 下没有缓存快照。先加 --pull（需要 root + adb）")

    if a.list:
        albums = wb.load_albums(dirs)
        rows = [v for v in albums.values() if v.get("trackCount")]
        rows.sort(key=lambda r: (-(r.get("isPodcast") or 0), -(r["trackCount"] or 0)))
        print(f"{'albumId':>12}  {'集数':>5}  {'播客':>4}  名称")
        for r in rows:
            print(f"{r['albumId']:>12}  {r['trackCount']:>5}  {'是' if r.get('isPodcast') else '  '}  {r['name'][:50]}")
        print(f"\n共 {len(rows)} 个专辑")
        return

    if not a.album:
        raise SystemExit("需要 --album 或 --list")

    data = build(a.album, dirs)
    out = a.out or os.path.join(wb.WORK, f"index_{a.album}.json")
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False)

    eps = data["eps"]
    have = [e for e in eps if e["text"]]
    withpi = [e for e in eps if e["posInfo"]]
    loose = [e for e in eps if e.get("match") == "loose"]
    print(f"专辑：{data['album'].get('name')}  ({a.album})")
    print(f"集数 {len(eps)} | 有文稿 {len(have)} | 有时间轴 {len(withpi)} | 总字数 {sum(len(e['text']) for e in have)}")
    if loose:
        print(f"⚠ 其中 {len(loose)} 集是按时长兜底匹配的（key 被前缀压缩），建议抽查：")
        for e in loose:
            print(f"    第{e['idx']}集 {e['title'][:34]}  {len(e['text'])}字")
    miss = [e for e in eps if not e["text"]]
    if miss:
        print(f"⚠ 缺文稿 {len(miss)} 集（用 warm.py 触发生成）：")
        for e in miss[:40]:
            print(f"    第{e['idx']}集 {e['title'][:40]}")
        if a.show_missing:
            print("  （以上即全部缺集）")
    print(f"索引已写入 {out}")


if __name__ == "__main__":
    main()
