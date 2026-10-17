#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出成果：一个目录 + 每集一个带时间戳的 md

用法
  python export.py --index index_3110116986.json --out "D:/播客/毛选心法"
  python export.py --index index_3110116986.json --out ... --no-links   # 目录表格不加链接
  python export.py --index index_3110116986.json --out ... --csv        # 额外输出一份 csv

产物
  <out>/目录.md            表格：集数 | 标题 | 时长 | 字数 | 句数 | 时间轴 | 首句
  <out>/001_标题.md        每集一个，逐句带 [mm:ss]
"""
import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wb


def ep_filename(e):
    return f"{e['idx']:03d}_{wb.safe_name(e['title'], 40)}.md"


def render_ep(e, album_name):
    rows = wb.slice_ep(e)
    head = [f"# 第 {e['idx']} 集 · {e['title']}", ""]
    meta = [f"*时长 {wb.fmt_time(e['duration'])}",
            f"{len(rows)} 句",
            f"{len(e['text'])} 字"]
    meta.append(album_name)
    head.append(" · ".join(meta) + "*")
    head.append("")
    if not rows:
        head.append("> （本集暂无 AI 文稿）")
        return "\n".join(head) + "\n"
    body = [f"[{wb.fmt_time(ms)}] {seg}" for ms, seg in rows]
    return "\n".join(head + body) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-links", action="store_true", help="目录表格的标题列不加 md 链接")
    ap.add_argument("--csv", action="store_true", help="额外输出 分集索引.csv")
    ap.add_argument("--name", help="目录标题（默认用专辑名）")
    a = ap.parse_args()

    data = json.load(open(a.index, encoding="utf-8"))
    eps = sorted(data["eps"], key=lambda e: e["idx"])
    album = data.get("album") or {}
    album_name = album.get("name") or "播客"
    title = a.name or album_name

    os.makedirs(a.out, exist_ok=True)
    for e in eps:
        open(os.path.join(a.out, ep_filename(e)), "w", encoding="utf-8").write(
            render_ep(e, album_name))
    print(f"已写 {len(eps)} 个单集文件")

    have = [e for e in eps if e["text"]]
    withpi = [e for e in eps if e["posInfo"]]
    L = [
        f"# {title} · 文稿目录",
        "",
        f"> 专辑 albumId：{album.get('albumId', '')}  ",
        f"> 集数 {len(eps)} 集；已收录文稿 {len(have)} 集，约 {sum(len(e['text']) for e in have)} 字  ",
        f"> 更新时间：{time.strftime('%Y-%m-%d %H:%M')}  ",
        f"> 每集文件按「集号_标题.md」命名，正文逐句带 [分:秒] 时间戳",
        "",
        "---",
        "",
        "| 集数 | 标题 | 时长 | 字数 | 句数 | 时间轴 | 首句 |",
        "| ---: | --- | ---: | ---: | ---: | :---: | --- |",
    ]
    for e in eps:
        first = (e["text"].split("\n")[0][:40] if e["text"] else "")
        first = first.replace("|", "\\|")
        t = e["title"].replace("|", "\\|")
        label = t if a.no_links else f"[{t}]({ep_filename(e)})"
        L.append(f"| {e['idx']} | {label} | {wb.fmt_time(e['duration'])} | "
                 f"{len(e['text'])} | {len(e['posInfo'])} | "
                 f"{'有' if e['posInfo'] else '无'} | {first} |")
    L.append("")
    open(os.path.join(a.out, "目录.md"), "w", encoding="utf-8").write("\n".join(L))
    print(f"已写 目录.md（{len(eps)} 行）")

    if a.csv:
        p = os.path.join(a.out, "分集索引.csv")
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["集数", "标题", "时长", "字数", "句数", "时间轴", "首句"])
            for e in eps:
                first = (e["text"].split("\n")[0][:40] if e["text"] else "")
                w.writerow([e["idx"], e["title"], wb.fmt_time(e["duration"]),
                            len(e["text"]), len(e["posInfo"]),
                            "有" if e["posInfo"] else "无", first])
        print(f"已写 分集索引.csv")

    missing = [e["idx"] for e in eps if not e["text"]]
    if missing:
        print(f"⚠ 仍有 {len(missing)} 集没有文稿：{missing[:20]}")
    print(f"输出目录：{os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
