#!/usr/bin/env python3
"""按通用组件设计契约审查项目组件（与组件库无关）。

用法:
    python3 check_contract.py src/components/DataFilterBar/index.tsx
    python3 check_contract.py src/components --recursive
    python3 check_contract.py src/ --recursive --json
    python3 check_contract.py src/components --recursive --format compliance

检查依据是 references/component-design.md 的七维契约，不针对任何具体组件库：
    1 角色      说不说得出「不解决什么」
    2 数据契约  形状/量级/可否自造/变更频率
    3 交互契约  含反悔与取消路径
    4 状态全枚举 12 态齐全，disabled 与 readonly 分开
    5 边界与代价  是否有「到 Y 程度会 Z」的表述
    6 变体轴    variant/size 等是否显式
    7 无障碍    键盘可达、焦点可见、图标按钮有名称

源码只能反映第 2/4/6/7 维的一部分；第 1/3/5 维要看规格文档，
故本脚本同时检查 .ui-kit/catalog/<Component>.md 是否存在且填全。

退出码: 0 = 无 error；1 = 有 error；2 = 配置错误
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SRC_EXT = (".tsx", ".ts", ".jsx", ".js", ".vue")
EXCLUDE_DIRS = {"node_modules", "dist", "build", ".git", ".ui-kit", "coverage",
                ".next", ".nuxt", "storybook", "__tests__"}

# ─────────────────────────────────────────────────────────────
# 状态全枚举：契约第 4 维要求 12 态齐全
#
# 逐项给 (状态名, 识别模式, 提示)。
# 平台差异：hover 在触屏平台不存在，由平台包负责处理，此处不判断。
# ─────────────────────────────────────────────────────────────

STATE_CHECKS = [
    ("disabled", r"\bdisabled\b|isDisabled|aria-disabled",
     "禁用态，且应有原因说明（灰着但不说为什么，用户会困惑）"),
    ("loading", r"\bloading\b|isLoading|spinner|skeleton|pending",
     "加载态。耗时 >1s 应有反馈，<300ms 不显示（会闪烁）"),
    ("error", r"\berror\b|\binvalid\b|hasError|validateStatus|校验失败",
     "错误态，且错误文案要说清「怎么改」而不只是「错了」"),
    ("empty", r"\bempty\b|noData|no-data|暂无数据|placeholder",
     "空状态。需区分「首次为空」（引导创建）与「筛选后为空」（引导清除筛选）"),
]

# disabled 与 readonly 必须分清，这是契约第 4 维的硬要求
READONLY_DISTINCT = [
    ("readOnly 存在但与 disabled 未区分", r"readOnly|readonly",
     "readonly（不可编辑但可读可复制，视觉不置灰）与 disabled（不可交互且置灰）"
     "是两个状态，规格文档必须分别定义。表单里混用是常见错误"),
]

# ─────────────────────────────────────────────────────────────
# 变体轴：契约第 6 维
# ─────────────────────────────────────────────────────────────

VARIANT_CHECKS = [
    ("size", r"\bsize\b|size=|'sm'|'md'|'lg'|small|medium|large",
     "尺寸变体。同页面混用多种尺寸会显得很乱"),
    ("variant", r"\bvariant\b|type=|'primary'|'default'|'ghost'|'text'",
     "形态变体。variant 轴存在可避免为每种样式复制组件"),
]

# ─────────────────────────────────────────────────────────────
# 无障碍：契约第 7 维
# ─────────────────────────────────────────────────────────────

A11Y_CHECKS = [
    ("a11y-outline", r"outline\s*:\s*['\"]?(none|0)",
     "error",
     "outline: none 未提供替代焦点样式。补 :focus-visible，"
     "或移除（鼠标点击也会触发 :focus，不可用它）"),
    ("a11y-icon-label", r"<(button|Button)[^>]*>\s*<(i|Icon|svg|Svg)\b",
     "warning",
     "图标按钮缺少无障碍名称。加 aria-label，"
     "否则读屏用户只听到「按钮」"),
    ("a11y-div-click", r"<div[^>]*onClick",
     "error",
     "可点击的 div 不可聚焦，键盘无法操作。改用 button，"
     "或补 role/tabIndex/onKeyDown"),
    ("a11y-img-alt", r"<img\b(?![^>]*alt=)",
     "warning",
     "img 缺 alt。装饰图用 alt=\"\"，信息图要写描述"),
]

# ─────────────────────────────────────────────────────────────
# 交互契约：契约第 3 维 —— 反悔与取消路径最容易漏
# ─────────────────────────────────────────────────────────────

INTERACTION_CHECKS = [
    ("int-revert", r"onClear|clearable|allowClear|onDeselect|onRemove|onReset",
     "可清除/反悔。选中后用户能否反悔？清除后回到什么状态？",
     "warning"),
    ("int-cancel", r"onCancel|onClose|onDismiss|onOpenChange",
     "取消/关闭路径。关闭后内部状态保留还是清空？下次打开是空的还是上次的？",
     "warning"),
]


class Finding:
    __slots__ = ("dim", "code", "level", "msg", "line", "hint")

    def __init__(self, dim, code, level, msg, line=0, hint=""):
        self.dim, self.code, self.level = dim, code, level
        self.msg, self.line, self.hint = msg, line, hint

    def as_dict(self):
        return {"dim": self.dim, "code": self.code, "level": self.level,
                "msg": self.msg, "line": self.line, "hint": self.hint}

    def __str__(self):
        loc = f"L{self.line}" if self.line else "  -"
        s = f"  [{self.level:7}] [{self.dim}] {loc:5} {self.msg}"
        return s + (f"\n{'':16}↳ {self.hint}" if self.hint else "")


def looks_like_component(text, path):
    """判断文件是否是组件而非工具/hook/样式。"""
    if str(path).lower().endswith(".vue"):
        return True
    if not re.search(r"<\s*[A-Z_a-z][\w.]*[\s/>]|return\s*\(|render\s*\(|"
                     r"defineComponent|<template>", text):
        return False
    return bool(re.search(r"export\s+(?:const|function|default)|defineComponent|<template>", text))


def is_hook_or_util(text, path):
    """排除 hook / 工具函数——它们没有状态与无障碍要求。"""
    base = Path(path).stem
    if re.match(r"^use[A-Z]", base):
        return True
    if re.search(r"^\s*export\s+(?:const|function)\s+use[A-Z]\w*", text, re.M):
        return True
    # 纯 hooks 文件目录
    if re.search(r"[\\/](hooks|utils)[\\/]", str(path).replace("\\", "/"), re.I):
        return True
    return False


def check_source(path, text):
    """检查源码能反映的维度：2/4/6/7。"""
    F = []
    rel = path.as_posix()

    # 状态全枚举（第 4 维）
    missing = []
    for name, pat, hint in STATE_CHECKS:
        if not re.search(pat, text, re.I):
            missing.append(name)
    if missing:
        F.append(Finding(
            "4-状态", "states-missing", "warning",
            f"状态覆盖可能不足，缺少: {', '.join(missing)}",
            hint="契约要求 12 态齐全（default/hover/focus/active/selected/"
                 "disabled/readonly/loading/error/empty）。"
                 "缺状态是最常见的体验差距来源"))

    for label, pat, hint in READONLY_DISTINCT:
        if re.search(pat, text, re.I) and not re.search(r"readOnly|readonly", text, re.I):
            continue
        if re.search(r"readOnly|readonly", text, re.I):
            # 有 readonly —— 查是否与 disabled 有区分说明
            if not re.search(r"只读|不可编辑|可读|readonly.*!==.*disabled|"
                             r"disabled.*!==.*readonly|区分", text, re.I):
                F.append(Finding("4-状态", "readonly-mixed", "warning", label,
                                 hint=hint))

    # 变体轴（第 6 维）
    for name, pat, hint in VARIANT_CHECKS:
        if not re.search(pat, text, re.I):
            F.append(Finding(
                "6-变体轴", f"variant-{name}", "warning",
                f"未见 {name} 变体定义",
                hint=hint + "。若组件确实只有单一形态，在规格文档注明，"
                            "避免下游为第二种样式复制组件"))

    # 无障碍（第 7 维）
    for code, pat, level, hint in A11Y_CHECKS:
        for m in re.finditer(pat, text, re.I):
            line = text[: m.start()].count("\n") + 1
            F.append(Finding("7-无障碍", code, level, hint.split("。")[0], line, hint))

    # 交互契约（第 3 维）
    for code, pat, hint, level in INTERACTION_CHECKS:
        if not re.search(pat, text, re.I):
            F.append(Finding("3-交互", code, level, hint, 0,
                             "源码里搜不到不代表没做，但契约要求规格文档写清——"
                             "见 .ui-kit/catalog/<Component>.md"))

    return F


def check_spec(spec_path, comp_name):
    """检查规格文档是否覆盖源码反映不了的维度：1/3/5。"""
    F = []
    if not spec_path.is_file():
        return [Finding(
            "1-角色", "spec-missing", "warning",
            f"缺少组件规格文档 {spec_path.name}",
            0,
            f"契约第 1/3/5 维（角色边界、交互反悔路径、边界代价）"
            f"无法从源码判断，必须有规格文档。模板见 "
            f"assets/component-catalog.md.tmpl")]

    try:
        spec = spec_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [Finding("1-角色", "spec-unreadable", "warning",
                        f"无法读取规格文档: {e}")]

    # 第 1 维：角色与边界
    if not re.search(r"不负责|不解决|边界|职责边界|什么时候.*不", spec):
        F.append(Finding("1-角色", "spec-role", "warning",
                         "规格未写「不解决什么」",
                         0, "不写边界，AI 会在不该用它的时候用它——"
                            "这是组件误用的主要来源"))

    # 第 1 节：形态消歧记录
    if not re.search(r"判定为|判定依据|消歧|requested|resolved", spec):
        F.append(Finding("1-角色", "spec-morphology", "warning",
                         "规格未记录形态消歧结论",
                         0, "下次同类需求要重新走一遍消歧。"
                            "记录通用形态描述，不要只写组件名（换库即失效）"))

    # 第 3 维：反悔与取消
    if not re.search(r"反悔|清除|取消|撤销|回退|重置", spec):
        F.append(Finding("3-交互", "spec-revert", "warning",
                         "规格未写反悔与取消路径",
                         0, "选中后能否反悔？取消后状态保留还是清空？"
                            "这两个是最容易漏、也是投诉重灾区"))

    # 第 5 维：边界与代价
    if not re.search(r"上限|超出|超过.*会|限制|失效|不适用|不适用于", spec):
        F.append(Finding("5-边界", "spec-limits", "warning",
                         "规格未写「到 Y 程度会 Z」式的边界",
                         0, "「支持大数据量」不是边界，"
                            "「超过 100 条会卡顿」才是"))

    return F


def collect(paths, recursive):
    out, seen = [], set()
    for p in paths:
        pp = Path(p)
        if pp.is_file() and pp.suffix in SRC_EXT:
            cands = [pp]
        elif pp.is_dir():
            cands = []
            for dp, dn, fn in os.walk(pp):
                if not recursive:
                    if Path(dp).resolve() != pp.resolve():
                        dn[:] = []
                        continue
                dn[:] = [d for d in dn if d not in EXCLUDE_DIRS and not d.startswith(".")]
                for f in fn:
                    if f.endswith(SRC_EXT):
                        cands.append(Path(dp) / f)
        else:
            continue
        for c in cands:
            r = c.resolve()
            if r not in seen:
                seen.add(r)
                out.append(c)
    return out


def guess_component_name(path, text):
    m = re.search(r"export\s+(?:const|function|class)\s+([A-Z]\w+)", text)
    if m:
        return m.group(1)
    stem = Path(path).stem
    return stem if re.match(r"^[A-Z]", stem) else None


def main():
    ap = argparse.ArgumentParser(
        description="按通用组件设计契约审查组件（与组件库无关）")
    ap.add_argument("paths", nargs="+", help="组件文件或目录")
    ap.add_argument("--recursive", action="store_true", default=True,
                    help="目录递归（默认即递归）")
    ap.add_argument("--spec-dir", default=".ui-kit/catalog",
                    help="规格文档目录，用于检查第 1/3/5 维")
    ap.add_argument("--no-spec", action="store_true",
                    help="跳过规格文档检查（只看源码）")
    ap.add_argument("--format", default="text", choices=["text", "json", "compliance"],
                    help="输出格式。compliance 按维度汇总覆盖率")
    ap.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = ap.parse_args()

    targets = collect(args.paths, args.recursive)
    if not targets:
        print("[error] 没有可检查的文件", file=sys.stderr)
        return 2

    spec_dir = Path(args.spec_dir)
    results = []
    for t in targets:
        try:
            text = t.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"[skip] 无法读取 {t}: {e}", file=sys.stderr)
            continue

        if not looks_like_component(text, t) or is_hook_or_util(text, t):
            continue

        findings = check_source(t, text)
        if not args.no_spec:
            name = guess_component_name(t, text)
            if name:
                findings += check_spec(spec_dir / f"{name}.md", name)

        results.append({"path": t.as_posix(), "findings": findings})

    if args.format == "json":
        print(json.dumps(
            [{"path": r["path"],
              "findings": [f.as_dict() for f in r["findings"]]} for r in results],
            ensure_ascii=False, indent=2))
        errs = sum(1 for r in results for f in r["findings"] if f.level == "error")
        return 1 if (errs or (args.strict and any(
            f.level == "warning" for r in results for f in r["findings"]))) else 0

    if args.format == "compliance":
        dims = ["1-角色", "2-数据", "3-交互", "4-状态", "5-边界", "6-变体轴", "7-无障碍"]
        print(f"组件契约覆盖情况（{len(results)} 个组件）\n")
        print(f"{'维度':<12} {'命中缺口':<10} 说明")
        print("-" * 62)
        for d in dims:
            hits = [f for r in results for f in r["findings"] if f.dim == d]
            print(f"{d:<12} {len(hits):<10} {hits[0].hint[:40] if hits else '—'}")
        print()
        total = len(results)
        full = sum(1 for r in results if not r["findings"])
        print(f"无缺口组件: {full}/{total}")
        return 0

    # text
    for r in results:
        if not r["findings"]:
            continue
        errs = sum(1 for f in r["findings"] if f.level == "error")
        warns = len(r["findings"]) - errs
        print(f"\n── {r['path']} [{errs} error / {warns} warning]")
        for f in sorted(r["findings"], key=lambda x: (x.dim, x.level)):
            print(str(f))

    errs = sum(1 for r in results for f in r["findings"] if f.level == "error")
    warns = sum(1 for r in results for f in r["findings"] if f.level == "warning")
    print(f"\n{'=' * 64}")
    print(f"检查 {len(results)} 个组件：{errs} error / {warns} warning")
    if args.no_spec:
        print("提示: 未检查规格文档（第 1/3/5 维无法从源码判断），"
              "去掉 --no-spec 可一并检查")
    if errs or (args.strict and warns):
        print("结果: 不通过")
        return 1
    print("结果: 通过。warning 项逐条判断是否适用，不适用要在规格文档注明原因")
    return 0


if __name__ == "__main__":
    sys.exit(main())
