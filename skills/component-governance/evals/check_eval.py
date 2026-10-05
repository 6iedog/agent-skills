#!/usr/bin/env python3
"""eval 断言检查器：把 agent 的实际输出与 evals.json 的断言比对。

断言是**可验证的事实**，不是主观描述。不同模型写法不同就该判过 ——
所以断言一律落在「出现过/未出现过某关键词」「问题数量」这类可数事实上。

用法:
    # 保存 agent 输出后检查
    python check_eval.py skills/component-create --output run.md
    python check_eval.py skills/component-create --output-dir workspace/iteration-1/eval-1
    python check_eval.py skills/component-create --list
    python check_eval.py skills/component-create --all --output-dir workspace/

断言类型:
    mentions            输出中应出现 expect_any 之一
    must_not_ask        输出中不应出现 expect_none 任一（用于「不该问的别问」）
    avoid               同上，别名
    first_question_topics 输出的第一个问句应命中 expect_any 之一
    question_count      问句数量应 ≤ max
    not_this_skill      不应进入本 skill 的流程词
    no_component_discussion  不应出现组件流程词
    runs_scripts        应提到调用了脚本
    not_creates_new     不应出现新建动作
    reads_conventions   应读取了产出物
    no_governance_flow  不应进入治理流程
    excludes_with_reason  排除方案时应带理由
    reads_project_first  应先查项目

退出码: 0 = 全部断言通过；1 = 有失败
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 中文问句识别：以问号结尾，或含"吗/呢/多少/几个/是否/哪种"等疑问词
Q_PATTERNS = [
    re.compile(r"[^。！？\n]*[？?][^。！？\n]*"),
    re.compile(r"[^。\n]{0,40}(?:多少条|多少个|几条|几个|是否|哪种|哪种类型|要不要|能不能|会不会|需不需要|有没有)[^。\n]{0,40}"),
]


def split_sentences(text):
    """把输出切成句子/问句片段。"""
    parts = []
    for p in Q_PATTERNS:
        for m in p.finditer(text):
            s = m.group().strip()
            if s:
                parts.append(s)
    # 去重保序
    seen, out = set(), []
    for p in parts:
        k = p[:40]
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def count_questions(text):
    return len(split_sentences(text))


def first_question(text):
    qs = split_sentences(text)
    return qs[0] if qs else ""


def check_assertion(a, text, case_id):
    """返回 (passed, reason)。"""
    t = a["type"]
    low = text.lower()

    if t == "mentions":
        words = a.get("expect_any", [])
        hit = [w for w in words if w.lower() in low]
        return bool(hit), (f"出现 {hit}" if hit else f"未出现 {words}")

    if t in ("must_not_ask", "avoid", "not_creates_new", "no_component_discussion",
             "no_governance_flow"):
        words = a.get("expect_none", [])
        hit = [w for w in words if w.lower() in low]
        return (not hit), (f"误含 {hit}" if hit else "正确避开")

    if t == "not_this_skill":
        words = a.get("expect_none", [])
        hit = [w for w in words if w.lower() in low]
        return (not hit), (f"误含 {hit}" if hit else "正确避开")

    if t == "first_question_topics":
        fq = first_question(text)
        if not fq:
            return False, "未识别到问句"
        words = a.get("expect_any", [])
        hit = [w for w in words if w.lower() in fq.lower()]
        return bool(hit), (f"首问命中 {hit}：{fq[:50]}" if hit else f"首问未命中 {words}：{fq[:50]}")

    if t == "question_count":
        n = count_questions(text)
        mx = a.get("max", 99)
        return n <= mx, f"问句 {n} 个（上限 {mx}）"

    if t == "runs_scripts":
        words = a.get("expect_any", ["scan_components", "check_tokens", "check_contract"])
        hit = [w for w in words if w in text]
        return bool(hit), (f"调用了 {hit}" if hit else "未调用脚本")

    if t in ("reads_conventions", "reads_project_first"):
        words = a.get("expect_any", ["conventions", "interaction-ux", "registry", ".ui-kit", "已有", "现有"])
        hit = [w for w in words if w.lower() in low]
        return bool(hit), (f"提到 {hit}" if hit else f"未提到 {words}")

    if t == "excludes_with_reason":
        words = a.get("expect_any", ["层级", "级联", "树形"])
        hit = [w for w in words if w in text]
        return bool(hit), (f"提到 {hit}" if hit else f"未提到 {words}")

    return False, f"未知断言类型 {t}"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description="检查 agent 输出是否满足 evals.json 的断言")
    ap.add_argument("skill_dir", help="skill 目录（含 evals/evals.json）")
    ap.add_argument("--output", help="agent 输出的文件")
    ap.add_argument("--output-dir", help="含多个输出的目录（文件名匹配 eval 编号）")
    ap.add_argument("--case", type=int, help="只检查指定用例 id")
    ap.add_argument("--all", action="store_true", help="检查所有用例（需配合 --output-dir）")
    ap.add_argument("--list", action="store_true", help="列出全部用例")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args()

    skill_dir = Path(args.skill_dir)
    ev_path = skill_dir / "evals" / "evals.json"
    if not ev_path.is_file():
        print(f"[error] 找不到 {ev_path}", file=sys.stderr)
        return 2

    spec = load(ev_path)
    evals = spec["evals"]

    if args.list:
        print(f"\n{skill_dir.name} —— {len(evals)} 个用例\n")
        type_mark = {"core": "★核心", "edge": "◇边界", "should_not_trigger": "⊘不该触发"}
        for e in evals:
            mark = type_mark.get(e["type"], e["type"])
            print(f"  [{e['id']}] {mark}")
            print(f"      {e['prompt']}")
            print(f"      期望：{e['expected_output'][:70]}")
            for a in e.get("assertions", []):
                print(f"        · {a['type']}: {a.get('expect_any') or a.get('expect_none') or a.get('max')}")
            print()
        return 0

    # 收集待检查的 (用例, 文本)
    cases = []
    if args.output:
        if args.case is None:
            print("[error] --output 需要配合 --case 指定用例 id", file=sys.stderr)
            return 2
        case = next((e for e in evals if e["id"] == args.case), None)
        if not case:
            print(f"[error] 无 id={args.case} 的用例", file=sys.stderr)
            return 2
        cases.append((case, Path(args.output).read_text(encoding="utf-8", errors="replace")))

    elif args.output_dir:
        d = Path(args.output_dir)
        for e in evals:
            if args.case and e["id"] != args.case:
                continue
            # 找目录里的输出文件
            cands = sorted(d.glob(f"*{e['id']}*")) + sorted(d.glob("*.md")) + sorted(d.glob("*.txt"))
            if cands:
                cases.append((e, cands[0].read_text(encoding="utf-8", errors="replace")))
            elif args.all:
                print(f"[skip] 用例 {e['id']}：{d} 下找不到输出", file=sys.stderr)

    else:
        print("[error] 需要 --output 或 --output-dir", file=sys.stderr)
        return 2

    if not cases:
        print("[error] 没有可检查的输出", file=sys.stderr)
        return 2

    # 逐条判定
    results = []
    total_pass = total_fail = 0
    for case, text in cases:
        print(f"\n{'='*66}")
        print(f"用例 {case['id']}  [{case['type']}]")
        print(f"提示：{case['prompt']}")
        print(f"{'-'*66}")
        for a in case.get("assertions", []):
            ok, reason = check_assertion(a, text, case["id"])
            mark = "[PASS]" if ok else "[FAIL]"
            print(f"  {mark} {a['type']:<26} {reason}")
            results.append({"case": case["id"], "assert": a["type"],
                            "passed": ok, "reason": reason})
            if ok:
                total_pass += 1
            else:
                total_fail += 1

    print(f"\n{'='*66}")
    print(f"通过 {total_pass} / 失败 {total_fail}")

    if args.json:
        print(json.dumps({"results": results,
                          "pass": total_pass, "fail": total_fail},
                         ensure_ascii=False, indent=2))

    if total_fail:
        print("结果: 存在失败断言")
        return 1
    print("结果: 全部断言通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
