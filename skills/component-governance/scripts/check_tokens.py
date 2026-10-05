#!/usr/bin/env python3
"""校验组件是否违反设计令牌与无障碍基础要求。

用法:
    python3 check_tokens.py <组件文件...> --tokens <项目>/.ui-kit/tokens.json
    python3 check_tokens.py src/components/ --tokens .ui-kit/tokens.json --recursive
    python3 check_tokens.py src/ --tokens .ui-kit/tokens.json --recursive --platform web

退出码: 0 = 通过（可含 warning）; 1 = 存在 error 级别问题
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SRC_EXT = (".tsx", ".ts", ".jsx", ".js", ".vue")

EXCLUDE_DIRS = {"node_modules", "dist", "build", ".git", ".ui-kit", "coverage", ".next"}

# 平台点击目标尺寸下限（px）
CLICK_TARGET_MIN = {"web": 24, "mobile": 44, "default": 24}

# 色值白名单：中性色阶、纯黑白、透明
NEUTRAL_COLOR_OK = re.compile(
    r"^#(?:fff|ffffff|000|000000|f5f5f5|eee|ddd|ccc|bbb|aaa|999|888|777|666|555|444|333|222|111)$", re.I
)

# 已知 CSS 变量白名单（非项目令牌也可接受）
CSS_VAR_OK = re.compile(
    r"^--("
    r"ant-|nsw-|el-|wot-|taro-|u-|v-|"
    r"color-|bg-|text-|border-|space-|radius|size-|z-|motion-"
    r")"
)


class Finding:
    __slots__ = ("level", "code", "msg", "line", "hint")

    def __init__(self, level, code, msg, line, hint=""):
        self.level, self.code, self.msg, self.line, self.hint = level, code, msg, line, hint

    def __str__(self):
        loc = f"L{self.line}" if self.line else "-"
        s = f"  [{self.level.upper():5}] {loc:6} {self.code} {self.msg}"
        return s + (f"\n           ↳ {self.hint}" if self.hint else "")


def load_tokens(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        print(f"[error] 无法解析 tokens 文件: {e}", file=sys.stderr)
        return None


def token_values(tokens):
    """从 tokens.json 收集全部字面量值，用于合法值判断。"""
    vals = set()

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, (str, int, float)):
            vals.add(str(node).strip())

    walk(tokens)
    return vals


def token_names(tokens):
    """收集令牌名（支持嵌套点号与连字符两种写法）。"""
    names = set()

    def walk(node, prefix=""):
        if isinstance(node, dict):
            has_leaf = any(not isinstance(v, dict) for v in node.values())
            for k, v in node.items():
                walk(v, f"{prefix}{k}." if not has_leaf or isinstance(v, dict) else f"{prefix}{k}")
        else:
            if prefix:
                names.add(prefix.rstrip("."))
                names.add(prefix.rstrip(".").replace(".", "-"))
                names.add(prefix.rstrip(".").replace(".", "_"))

    walk(tokens)
    return names


# ---------- 检查项 ----------

def check_hardcoded_color(text, lines, findings):
    """硬编码色值。"""
    patterns = [
        (r"(?:color|background|backgroundColor|borderColor|fill|stroke)\s*[:=]\s*['\"]?(#[0-9a-fA-F]{3,8}\b)", "color-hex"),
        (r"(?:color|background|backgroundColor|borderColor)\s*[:=]\s*['\"]?(rgba?\([^)]+\))", "color-rgb"),
        (r"(?:color|background)\s*[:=]\s*['\"](#{3,8})['\"]", "color-hex"),
    ]
    for pat, code in patterns:
        for m in re.finditer(pat, text):
            val = m.group(1)
            if NEUTRAL_COLOR_OK.match(val) or val.lower() in ("rgba(0, 0, 0, 0)", "transparent"):
                continue
            line = text[: m.start()].count("\n") + 1
            findings.append(Finding(
                "error", code, f"硬编码色值 {val}",
                line, "改用 tokens 中的语义色，如 var(--color-primary) / theme.color.primary"))


def check_magic_number(text, lines, tokens, valid_values, findings):
    """魔法圆角与间距。"""
    rules = [
        (r"borderRadius\s*[:=]\s*['\"]?(\d+)px", "magic-radius", "圆角", "var(--size-radius-md)"),
        (r"(?:padding|paddingTop|paddingBottom|paddingLeft|paddingRight)\s*[:=]\s*['\"`]?(\d+)px",
         "magic-space", "内边距", "var(--size-space-md)"),
        (r"(?:margin|marginTop|marginBottom|marginLeft|marginRight)\s*[:=]\s*['\"`]?(\d+)px",
         "magic-space", "外边距", "var(--size-space-md)"),
    ]
    for pat, code, label, hint in rules:
        for m in re.finditer(pat, text):
            val = m.group(1)
            if val in valid_values or val in ("0", "0px"):
                continue
            line = text[: m.start()].count("\n") + 1
            findings.append(Finding(
                "warning", code, f"魔法{label} {val}px 不在 tokens 中",
                line, f"改用 {hint}，或把 {val}px 加入 tokens.json 后重跑"))


def check_magic_zindex(text, lines, findings):
    for m in re.finditer(r"zIndex\s*[:=]\s*['\"]?(\d{3,5})", text):
        val = m.group(1)
        if val in ("9999", "99999", "10000"):
            line = text[: m.start()].count("\n") + 1
            findings.append(Finding(
                "error", "magic-zindex", f"z-index {val} 属于魔法值",
                line, "改用 tokens 中的 z-index 令牌，如 z-index.dropdown / z-index.modal"))


def check_a11y(text, findings):
    """无障碍基础项。"""
    # outline: none 未配套 focus-visible
    # 覆盖三种写法：CSS 的 outline: none / JSX 的 outline: 'none' / 对象样式 outline: 0
    for m in re.finditer(r"outline\s*:\s*['\"]?(none|0)['\"]?", text, re.I):
        ctx = text[max(0, m.start() - 400): m.start() + 400]
        if "focus-visible" not in ctx and ":focus" not in ctx and "focus-within" not in ctx:
            line = text[: m.start()].count("\n") + 1
            findings.append(Finding(
                "error", "a11y-focus", f"outline: {m.group(1)} 未提供替代焦点样式",
                line, "补 :focus-visible 样式，或移除 outline: none（鼠标点击也会触发 :focus，不可用它）"))

    # 图标按钮缺 aria-label
    for m in re.finditer(r"<(\w+)([^>]*?)(?:icon|type=\"button\")([^>]*)>", text, re.I):
        tag, pre, post = m.group(1), m.group(2), m.group(3)
        attrs = pre + post
        if tag.lower() in ("img", "input", "select", "textarea"):
            continue
        if "aria-label" in attrs or "aria-labelledby" in attrs or "title" in attrs:
            continue
        body = text[m.end(): m.end() + 400]
        if not re.search(r"<(Icon|i|svg|Svg|span)\b", body, re.I):
            continue
        if not re.search(r"aria-label|title=", body[:300]):
            line = text[: m.start()].count("\n") + 1
            findings.append(Finding(
                "warning", "a11y-aria", f"<{tag}> 为图标类控件但缺少 aria-label",
                line, "图标按钮必须有无障碍名称，否则读屏用户无法识别"))


def check_click_target(text, findings, platform):
    """点击目标尺寸。

    需同时覆盖 `width: 24px` 与 JSX 对象样式里的裸数字 `width: 24`
    （React 内联样式不带单位是常态，只匹配 px 会漏掉大量真实违规）。
    """
    minimum = CLICK_TARGET_MIN.get(platform, 24)
    pats = [
        (r"(?:^|[;{\s])(?:min-)?(?:width|height)\s*:\s*['\"]?(\d+)(?:px)?['\"]?", "size"),
        (r"(?:minWidth|minHeight|size)\s*[:=]\s*['\"]?(\d+)(?:px)?", "size"),
    ]
    reported = set()
    for pat, _ in pats:
        for m in re.finditer(pat, text, re.I):
            val = int(m.group(1))
            if val == 0 or val >= 400:      # 0 与超大值不适用
                continue
            line = text[: m.start()].count("\n") + 1
            key = (line, val)
            if key in reported:
                continue
            if val < minimum:
                reported.add(key)
                findings.append(Finding(
                    "warning" if platform == "web" else "error",
                    "target-size",
                    f"尺寸 {val}px 小于 {platform} 平台点击目标下限 {minimum}px",
                    line, f"触控热区应 ≥ {minimum}px。可用伪元素扩大热区而不改视觉尺寸："
                          f".el::after {{ position:absolute; inset:-{max(0,(minimum-val)//2)}px }}" if platform == "web"
                          else f"触控热区必须 ≥ {minimum}px，请调整控件尺寸"))


def check_states(text, findings, ctype_hint=None):
    """状态覆盖度：判断是否遗漏关键状态。

    只对真正的 UI 组件生效 —— 对 hook / util / 工具文件报"状态缺失"是误报，
    会淹没真实问题。
    """
    # 识别是否含 JSX；无 JSX 一律跳过
    if not re.search(r"<\s*[A-Z_a-z][\w.]*[\s/>]|return\s*\(|render\s*\(|defineComponent|<template>", text):
        return
    # 纯样式文件、纯类型文件也跳过
    if not re.search(r"export\s+(?:const|function|default)|defineComponent|<template>", text):
        return

    required = {
        "disabled": r"disabled",
        "loading": r"loading|spinner|skeleton|pending",
        "error": r"error|invalid|hasError",
        "empty": r"empty|noData|no-data|暂无",
    }
    missing = [k for k, pat in required.items() if not re.search(pat, text, re.I)]
    if len(missing) >= 3:
        findings.append(Finding(
            "warning", "states-missing",
            f"状态覆盖可能不足，缺少: {', '.join(missing)}",
            0, "组件规格必须全枚举状态（default/hover/focus/active/selected/disabled/"
               "readonly/loading/error/empty），详见 interaction-ux.md 第 12 节"))


def check_prefers_reduced_motion(text, findings):
    if "transition" in text or "animation" in text:
        if "prefers-reduced-motion" not in text:
            findings.append(Finding(
                "warning", "a11y-motion", "存在动效但未处理 prefers-reduced-motion",
                0, "补充 @media (prefers-reduced-motion: reduce) 降级"))


def check_disabled_reason(text, findings):
    """禁用态是否有原因说明。"""
    if not re.search(r"\bdisabled\b", text):
        return
    if re.search(r"Tooltip|title=|说明|reason|tip|原因", text):
        return
    findings.append(Finding(
        "warning", "disabled-noreason", "存在 disabled 态但未见原因说明",
        0, "禁用态需通过 Tooltip 或文案说明原因，否则用户不知为何不可用"))


def check_file(path: Path, tokens, platform, valid_values, quiet=False):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [Finding("error", "read-fail", f"无法读取文件: {e}", 0)], 0

    if re.search(r"^\s*(\*|/\*|//)\s*(eslint|@ts-nocheck|prettier)", text) and len(text) < 200:
        return [], 0

    lines = text.split("\n")
    findings = []
    check_hardcoded_color(text, lines, findings)
    check_magic_number(text, lines, tokens, valid_values, findings)
    check_magic_zindex(text, lines, findings)
    check_a11y(text, findings)
    check_click_target(text, findings, platform)
    check_states(text, findings)
    check_prefers_reduced_motion(text, findings)
    check_disabled_reason(text, findings)
    return findings, len(lines)


def collect_targets(paths, recursive=True):
    """收集待检查文件。

    目录一律递归 —— 组件几乎总在 src/components/<Name>/index.tsx 这种子目录里。
    非递归只取顶层文件会让"传了个目录却漏掉全部子目录组件"成为静默失败，
    这类静默失败比报错更危险：看起来校验通过了，实际什么都没查。
    """
    out = []
    for p in paths:
        pp = Path(p)
        if pp.is_file() and pp.suffix in SRC_EXT:
            out.append(pp)
        elif pp.is_dir():
            for dp, dn, fn in os.walk(pp):
                dn[:] = [d for d in dn if d not in EXCLUDE_DIRS and not d.startswith(".")]
                for f in fn:
                    if f.endswith(SRC_EXT):
                        out.append(Path(dp) / f)
    seen, uniq = set(), []
    for f in out:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    return uniq


def main():
    ap = argparse.ArgumentParser(description="校验组件令牌一致性与无障碍基础项")
    ap.add_argument("paths", nargs="+", help="组件文件或目录")
    ap.add_argument("--tokens", required=True, help="tokens.json 路径")
    ap.add_argument("--platform", default="web", choices=["web", "mobile"], help="平台，影响点击目标阈值")
    ap.add_argument("--recursive", action="store_true", default=True,
                    help="目录递归（默认即递归，此参数仅为兼容保留）")
    ap.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = ap.parse_args()

    token_path = Path(args.tokens)
    tokens = load_tokens(token_path)
    if tokens is None:
        print(f"[error] 无法加载 tokens: {token_path}", file=sys.stderr)
        print("        若项目尚未初始化令牌，请先初始化 .ui-kit/tokens.json", file=sys.stderr)
        return 2

    valid_values = token_values(tokens)
    valid_names = token_names(tokens)
    print(f"[i] 令牌: {len(valid_values)} 个值 / {len(valid_names)} 个名字 | 平台: {args.platform}")

    targets = collect_targets(args.paths, args.recursive)
    if not targets:
        print("[error] 没有可检查的文件", file=sys.stderr)
        return 2

    total = {"error": 0, "warning": 0}
    for t in targets:
        findings, nlines = check_file(t, tokens, args.platform, valid_values)
        if not findings:
            continue
        errs = sum(1 for f in findings if f.level == "error")
        warns = sum(1 for f in findings if f.level == "warning")
        total["error"] += errs
        total["warning"] += warns
        rel = t.as_posix()
        print(f"\n── {rel} ({nlines} 行) [{errs} error / {warns} warning]")
        for f in findings:
            print(str(f))

    print(f"\n{'=' * 60}")
    print(f"检查 {len(targets)} 个文件：{total['error']} error / {total['warning']} warning")
    if total["error"] or (args.strict and total["warning"]):
        print("结果: 不通过 —— 硬编码与 a11y 硬性问题需当场修复，不要留给用户")
        return 1
    if total["warning"]:
        print("结果: 通过（有待确认项）—— 逐条判断是否需要处理，不适用项说明原因")
    else:
        print("结果: 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
