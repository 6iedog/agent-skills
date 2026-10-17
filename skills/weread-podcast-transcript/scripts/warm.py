#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""触发 AI 文稿生成并落库（微信读书必须"打开过该集文稿页"才会缓存）

用法
  python warm.py --index index_3110116986.json --missing        # 只补缺的集
  python warm.py --index index_3110116986.json --range 1 20     # 只跑第 1~20 集
  python warm.py --index index_3110116986.json --ep 5 --ep 65   # 指定若干集
  python warm.py --index ... --missing --wait 25 --pull         # 结束后自动拉缓存重建索引

要点（踩过的坑）
  · 播放中走完一集会**自动跳下一集**，文稿页也跟着变 → 每切一集都要先暂停
  · AI 文稿页会**跟随播放自动滚动** → 进入前先暂停
  · 播放器有动画时 uiautomator dump 会失败并返回旧 XML → 必须重试（wb.rdump 已处理）
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wb

BTN_BACK, BTN_LYRIC, BTN_PREV, BTN_NEXT, BTN_CATALOG = (46, 78), (109, 664), (451, 664), (1149, 664), (1490, 664)


def ensure_player(max_try=6):
    for _ in range(max_try):
        p, s = wb.state()
        if p:
            return True
        if s:
            wb.tap(*BTN_BACK, wait=2.2)
        else:
            wb.shp(["shell", "monkey -p com.tencent.weread -c android.intent.category.LAUNCHER 1"])
            time.sleep(4)
    return wb.state()[0]


def catalog_jump(title, max_scroll=70):
    """在「目录」面板里按标题找集并点击"""
    wb.tap(*BTN_CATALOG, wait=2.0)
    for i in range(max_scroll):
        hit = None
        for b, r, t, d in wb.nodes():
            if t.strip() == title.strip():
                hit = b
                break
        if hit:
            import re
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", hit)
            x1, y1, x2, y2 = map(int, m.groups())
            wb.tap((x1 + x2) // 2, (y1 + y2) // 2, wait=3.0)
            return True
        wb.swipe(800, 850, 800, 430, 300)
        time.sleep(0.9)
    wb.shp(["shell", "input keyevent 4"])
    time.sleep(1.2)
    return False


def goto(target, eps):
    """翻到指定集：近的用上一首/下一首，远的先试目录跳转"""
    by_idx = {e["idx"]: e for e in eps}
    cur = wb.cur_title()
    cur_i = next((e["idx"] for e in eps if e["title"] == cur), None)
    if cur == target["title"]:
        return True
    if cur_i is None or abs(cur_i - target["idx"]) > 6:
        if catalog_jump(target["title"]) and wb.cur_title() == target["title"]:
            wb.pause()
            return True
        cur_i = next((e["idx"] for e in eps if e["title"] == wb.cur_title()), cur_i or target["idx"])
    for _ in range(240):
        cur = wb.cur_title()
        if cur == target["title"]:
            wb.pause()
            return True
        cidx = next((e["idx"] for e in eps if e["title"] == cur), None)
        if cidx is None:
            wb.pause()
            return False
        btn = BTN_PREV if cidx > target["idx"] else BTN_NEXT
        wb.tap(*btn, wait=3.2)
        wb.pause()
    return False


def open_lyric(wait=20):
    """打开 AI 文稿页并等待生成"""
    for _ in range(4):
        wb.tap(*BTN_LYRIC, wait=3.5)
        if wb.state()[1]:
            break
    else:
        return False
    time.sleep(wait)
    return wb.state()[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--missing", action="store_true", help="只处理还没有文稿的集")
    ap.add_argument("--range", nargs=2, type=int, metavar=("FROM", "TO"))
    ap.add_argument("--ep", action="append", type=int, default=[])
    ap.add_argument("--wait", type=int, default=20, help="每集打开文稿后等待秒数")
    ap.add_argument("--pull", action="store_true", help="结束后拉缓存并重建索引")
    a = ap.parse_args()

    data = json.load(open(a.index, encoding="utf-8"))
    eps = data["eps"]
    targets = []
    if a.ep:
        targets = [e for e in eps if e["idx"] in set(a.ep)]
    elif a.range:
        targets = [e for e in eps if a.range[0] <= e["idx"] <= a.range[1]]
    elif a.missing:
        targets = [e for e in eps if not e["text"]]
    if not targets:
        print("没有需要处理的集")
        return
    print(f"待处理 {len(targets)} 集：{[e['idx'] for e in targets][:20]}…")

    wb.connect()
    if not ensure_player():
        raise SystemExit("未回到播放页，请先手动打开某集的播放页")
    wb.pause()

    ok = 0
    for k, e in enumerate(targets, 1):
        print(f"[{k}/{len(targets)}] 第{e['idx']}集 {e['title'][:30]}", flush=True)
        if not goto(e, eps):
            print("    ! 定位失败，跳过", flush=True)
            continue
        if not open_lyric(a.wait):
            print("    ! 文稿页未打开", flush=True)
            continue
        ok += 1
        wb.tap(*BTN_BACK, wait=2.2)
        time.sleep(0.5)
    print(f"完成 {ok}/{len(targets)} 集")

    if a.pull:
        print("拉取缓存…")
        for d in wb.pull_db("snap"):
            print("  ", d)
        import scan
        sys.argv = ["scan.py", "--album", str(data["album"]["albumId"]),
                    "--out", a.index]
        scan.main()


if __name__ == "__main__":
    main()
