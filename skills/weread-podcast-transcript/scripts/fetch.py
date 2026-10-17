#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按位置取文案（不导出整套，只取需要的一段）

用法
  python fetch.py --index index_X.json --ep 5                      整集
  python fetch.py --index index_X.json --ep 5 --from 01:30         1:30 之后
  python fetch.py --index index_X.json --ep 5 --from 01:00 --to 02:30
  python fetch.py --index index_X.json --q 关键词 --from 06:50      按标题定位，不用记集号
  python fetch.py --index index_X.json --find 关键词                跨集搜索：哪一集哪一秒
  python fetch.py --index index_X.json --list                      列集
  python fetch.py --index index_X.json --ep 5 --stamps --out a.md  每句加时间戳并写文件
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--ep", type=int)
    ap.add_argument("--q", help="标题关键词")
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--to", dest="to")
    ap.add_argument("--stamps", action="store_true")
    ap.add_argument("--find", help="跨集搜索关键词")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()

    data = json.load(open(a.index, encoding="utf-8"))
    eps = sorted(data["eps"], key=lambda e: e["idx"])

    if a.list:
        for e in eps:
            print(f"{e['idx']:3d}  {wb.fmt_time(e['duration']):>5}  "
                  f"{len(e['text']):5d}字  {e['title']}")
        return

    if a.find:
        print(f"搜索「{a.find}」：")
        n = 0
        for e in eps:
            if a.find not in (e["text"] or ""):
                continue
            n += 1
            for ms, seg in wb.slice_ep(e):
                if a.find in seg:
                    print(f"  第{e['idx']:3d}集 [{wb.fmt_time(ms)}] {e['title'][:34]}")
                    print(f"        {seg[:70]}")
                    break
        if not n:
            print("  没找到")
        return

    if a.ep:
        e = next((x for x in eps if x["idx"] == a.ep), None)
        if not e:
            sys.exit(f"没有第 {a.ep} 集")
    elif a.q:
        hit = [x for x in eps if a.q in x["title"]]
        if not hit:
            sys.exit(f"标题里没有「{a.q}」")
        for x in hit[1:]:
            print(f"（另有 第{x['idx']}集 {x['title'][:30]}）", file=sys.stderr)
        e = hit[0]
    else:
        sys.exit("需要 --ep / --q / --find / --list")

    t0, t1 = wb.parse_time(a.frm), wb.parse_time(a.to)
    rows = wb.slice_ep(e, t0, t1)
    dur = e["duration"] or (e["posInfo"][-1]["ms_end"] if e["posInfo"] else 0)
    t0e = 0 if t0 is None else t0
    t1e = dur if t1 is None else min(t1, dur)

    head = [f"# 第 {e['idx']} 集 · {e['title']}",
            (f"*时长 {wb.fmt_time(dur)}"
             + (f" · 区间 {wb.fmt_time(t0e)}-{wb.fmt_time(t1e)}" if (t0 or t1) else "")
             + f" · 共 {len(rows)} 句 · {sum(len(s) for _, s in rows)} 字*"),
            ""]
    body = [f"[{wb.fmt_time(ms)}] {seg}" if a.stamps else seg for ms, seg in rows]
    text = "\n".join(head + body)

    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
        print(f"已写入 {a.out}（{len(rows)} 句）")
    else:
        print(text)


if __name__ == "__main__":
    main()
