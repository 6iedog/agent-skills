#!/usr/bin/env python3
"""扫描项目组件，生成 .ui-kit/registry.json（带指纹的增量索引）。

用法:
    python3 scan_components.py <项目根> --out <项目根>/.ui-kit/registry.json
    python3 scan_components.py <项目根> --out ... --roots src/components src/ui --force

行为:
    - 优先用 git ls-files 取文件列表（比递归快一个数量级），失败回落 os.walk
    - 命中指纹的文件只更新索引，不重读内容
    - 失配文件重新解析
    - 明确排除测试/story/声明文件与构建产物
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# 默认扫描根：按常见约定排列，实际以项目 package.json 声明为准
DEFAULT_ROOTS = ["src/components", "src/ui", "src/widgets", "components", "src/component"]

# 明确排除：测试、story、类型声明、构建产物、缓存
EXCLUDE_PATTERNS = [
    r"\.test\.", r"\.spec\.", r"\.stories\.", r"\.story\.",
    r"__tests__", r"__mocks__", r"__snapshots__",
    r"\.d\.ts$", r"\.min\.", r"\.map$",
]
EXCLUDE_DIRS = {
    "node_modules", "dist", "build", "out", ".next", ".nuxt", ".git",
    ".ui-kit", ".turbo", ".cache", "coverage", ".workbuddy", ".vscode", ".idea",
}

# 业务语义标签：从中英文标识中提取，供模糊查询用。
# 每条为 (正则, 标签)。正则需带边界，避免 "Table" 命中 "tab"、"useNav" 命中 "nav" 之类误报。
TAG_RULES = [
    (r"filter|search|筛选|过滤", "筛选"),
    (r"\blist\b|\btable\b|\bgrid\b|列表|表格", "列表"),
    (r"\bform\b|表单", "表单"),
    (r"\bselect\b|\bpicker\b|\bchoose\b|选择", "选择"),
    (r"\binput\b|\bfield\b|输入", "输入"),
    (r"\bmodal\b|\bdialog\b|弹窗|对话框", "弹窗"),
    (r"\bdrawer\b|抽屉", "抽屉"),
    (r"\bupload\b|上传", "上传"),
    (r"\beditor\b|编辑", "编辑"),
    (r"\bdetail\b|详情", "详情"),
    (r"\bcard\b|卡片", "卡片"),
    (r"\bnav\b|\bmenu\b|\btabs?\b|\bbreadcrumb\b|导航|菜单", "导航"),
    (r"\bempty\b|空状态", "空状态"),
    (r"\bpagination\b|分页", "分页"),
    (r"\bchart\b|\bgraph\b|图表", "图表"),
    (r"\bpopover\b|\btooltip\b|气泡|提示", "气泡提示"),
    (r"\bbutton\b|\bbtn\b|按钮", "按钮"),
    (r"\blayout\b|布局", "布局"),
    (r"\bpanel\b|面板", "面板"),
]

UI_LIB_HINTS = {
    "antd": "antd", "@ant-design": "antd", "element-plus": "element-plus",
    "vuetify": "vuetify", "@mui/material": "mui", "chakra-ui": "chakra-ui",
    "@radix-ui": "radix", "shadcn": "shadcn", "vant": "vant",
    "antd-mobile": "antd-mobile", "@tarojs": "taro", "daisyui": "daisyui",
}


def norm_list(args, flag):
    """合并命令行多次传参与默认值。"""
    out = list(args) if args else []
    return out or []


def run_git_ls_files(root: Path):
    """尝试用 git ls-files 取文件列表。返回 None 表示不可用。"""
    try:
        res = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(root), capture_output=True, timeout=30,
        )
        if res.returncode != 0 or not res.stdout:
            return None
        rels = [p.decode("utf-8", "replace") for p in res.stdout.split(b"\0") if p]
        return [r for r in rels if r]
    except Exception:
        return None


def walk_files(root: Path, roots):
    """递归遍历（非 git 项目回落方案）。"""
    found = []
    for r in roots:
        base = root / r
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")]
            for fn in filenames:
                found.append(str((Path(dirpath) / fn).relative_to(root)).replace(os.sep, "/"))
    return found


def is_excluded(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    return any(re.search(pat, rel) for pat in EXCLUDE_PATTERNS)


def extract_tags(text: str):
    """按规则提取业务语义标签。"""
    tags = set()
    for pat, tag in TAG_RULES:
        if re.search(pat, text, re.I):
            tags.add(tag)
    return sorted(tags)


def detect_stack(root: Path):
    """从 package.json 识别框架与 UI 库。"""
    pkg = root / "package.json"
    if not pkg.is_file():
        return {"framework": "unknown", "ui_library": "unknown", "ui_libs": []}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {"framework": "unknown", "ui_library": "unknown", "ui_libs": []}

    deps = {}
    deps.update(data.get("dependencies") or {})
    deps.update(data.get("devDependencies") or {})

    libs = []
    for dep in deps:
        for hint, name in UI_LIB_HINTS.items():
            if dep.startswith(hint) and name not in libs:
                libs.append(name)
    framework = "vue" if "vue" in deps else ("react" if "react" in deps else "unknown")
    return {"framework": framework, "ui_library": libs[0] if libs else "unknown", "ui_libs": libs}


def collect_library_imports(text: str, libs):
    """提取从 UI 库导入的组件名。"""
    found = set()
    for lib in libs:
        if not lib:
            continue
        pats = [
            rf"import\s*\{{([^}}]+)\}}\s*from\s*['\"]{re.escape(lib)}(?:/[^'\"]*)?['\"]",
            rf"from\s*['\"]{re.escape(lib)}(?:/[^'\"]*)?['\"]",
        ]
        for pat in pats:
            for m in re.finditer(pat, text):
                if m.groups():
                    for part in m.group(1).split(","):
                        nm = part.strip().split(" as ")[0].strip()
                        if nm:
                            found.add(f"{lib}:{nm}")
                else:
                    imp = re.findall(r"import\s+(\w+)", m.group(0))
                    found.update(f"{lib}:{n}" for n in imp)
    return sorted(found)


def detect_local_deps(text: str, local_names, self_name: str):
    """提取对项目内其他组件的依赖。

    只认相对路径导入（./ 或 ../），避免把同名库组件误判为本地依赖。
    """
    deps = set()
    candidates = local_names - {self_name, "index", "Index"}
    for name in candidates:
        # 相对路径导入：from './Button' / from "../Table/Table"
        pats = [
            rf"from\s*['\"](?:\./|\.\./)[^'\"]*{re.escape(name)}['\"]",
            rf"from\s*['\"](?:@/|\$)/[^'\"]*{re.escape(name)}['\"]",
        ]
        if any(re.search(p, text) for p in pats):
            deps.add(name)
    return sorted(deps)


def collect_exports(text: str, fname: str):
    """解析导出方式与组件名。"""
    names = set()
    for m in re.finditer(r"export\s+(?:default\s+)?(?:const|function|class)\s+(\w+)", text):
        names.add(m.group(1))
    for m in re.finditer(r"export\s*\{([^}]+)\}", text):
        for part in m.group(1).split(","):
            nm = part.strip().split(" as ")[-1].strip()
            if nm and nm not in ("default", "type"):
                names.add(nm)
    style = "default" if re.search(r"export\s+default", text) else ("named" if names else "unknown")
    if not names and style == "default":
        guess = re.sub(r"\.(tsx|ts|jsx|js|vue)$", "", fname)
        guess = re.sub(r"^(index|Index)$", "default", guess)
        if guess != "default":
            names.add(guess)
    return sorted(names), style


def component_type(text: str, path: str, lib_imports=None):
    """粗判组件类型：composite / single / hook / util。

    composite 判定以"组合了什么"为准，比看语法可靠：
    组合了 ≥2 个库组件，或导出了子组件（compound components），即视为复合组件。
    """
    if re.search(r"export\s+(?:const|function)\s+use[A-Z]\w*", text) and "<" not in text:
        return "hook"
    # 无 JSX → 工具函数
    if not re.search(r"<\s*[A-Z_a-z][\w.]*[^>]*>|return\s*\(|render\s*\(", text):
        return "util"
    if path.lower().endswith(".vue"):
        return "single"
    # 复合：组合了多个库组件
    if len(lib_imports or []) >= 2:
        return "composite"
    # 复合：导出了子组件（compound API），如 Select.Option
    if re.search(r"export\s+(?:const|function)\s+(\w+)[^\n]*\n[\s\S]{0,200}?\1\s*\.", text):
        return "composite"
    return "single"


def guess_summary(text: str, name: str, path: str, tags=None, lib_imports=None, ctype="single"):
    """从文件头注释或 JSDoc 提取一句话能力描述。

    提取不到时用结构化信号兜底（标签 + 组合的库组件），
    因为 capability_summary 是选型时判断"能否覆盖需求"的主要依据，
    写成 "name（path）" 这种无信息量的字符串等于没写。
    """
    m = re.search(r"/\*\*\s*\n\s*\*\s*([^\n*]{4,120})", text)
    if m:
        s = m.group(1).strip()
        s = re.sub(r"^@summary\s*", "", s)
        if not s.startswith("@"):
            return s
    m2 = re.search(r"//\s*([^\n]{6,120})", text)
    if m2:
        s = m2.group(1).strip()
        if s and not s.startswith(("eslint", "prettier", "ts-", "vue-tsc", "//#")):
            return s

    # 兜底：用标签与库组件拼出可判断的描述
    bits = []
    if tags:
        bits.append("、".join(tags[:3]))
    if lib_imports:
        composed = [i.split(":", 1)[-1] for i in lib_imports[:4]]
        bits.append(f"组合 {', '.join(composed)}")
    if bits:
        kind = {"composite": "复合组件", "hook": "Hook", "util": "工具函数"}.get(ctype, "组件")
        return f"{kind}（{ '；'.join(bits) }）—— 无文件头描述，判断能力请直接查看 {path}"
    return f"未提取到描述，判断能力请直接查看 {path}"


def token_refs(text: str):
    """提取使用的令牌引用。"""
    out = set()
    for m in re.finditer(r"var\(--([a-z0-9-]+)\)", text):
        out.add(m.group(1))
    for m in re.finditer(r"\$([a-z][a-zA-Z0-9]*)", text):
        out.add(m.group(1))
    return sorted(out)[:30]


def variant_refs(text: str):
    out = set()
    for m in re.finditer(r"(?:variant|size|type)\s*[:=]\s*['\"]([\w-]+)['\"]", text):
        out.add(m.group(1))
    return sorted(out)[:12]


def build_component(root: Path, rel: str, old: dict, libs):
    abs_path = root / rel
    try:
        st = abs_path.stat()
    except OSError:
        return None
    mtime, size = int(st.st_mtime), st.st_size

    # 指纹命中且未强制 → 复用旧解析结果
    fp = old.get("fingerprint") or {}
    if fp.get("mtime") == mtime and fp.get("size") == size and old.get("name"):
        return old

    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    fname = Path(rel).stem
    exports, style = collect_exports(text, fname)
    name = exports[0] if exports else fname
    lib_imports = collect_library_imports(text, libs)
    ctype = component_type(text, rel, lib_imports)
    tags = extract_tags(rel + " " + " ".join(exports) + " " + text[:1500])

    return {
        "name": name,
        "path": rel,
        "type": ctype,
        "exports": {e: style for e in exports} or {name: style},
        "depends_on": [],
        "composes_library": lib_imports,
        "tags": tags,
        "variants": variant_refs(text),
        "platform": [],
        "capability_summary": guess_summary(text, name, rel, tags, lib_imports, ctype),
        "spec": f"catalog/{name}.md",
        "tokens_used": token_refs(text),
        "fingerprint": {"mtime": mtime, "size": size},
    }


def main():
    ap = argparse.ArgumentParser(description="扫描项目组件生成 registry")
    ap.add_argument("root", help="项目根目录")
    ap.add_argument("--out", required=True, help="registry.json 输出路径")
    ap.add_argument("--roots", nargs="*", default=None, help="扫描根目录（可多个）")
    ap.add_argument("--force", action="store_true", help="忽略指纹，全量重新解析")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[error] 项目根不存在: {root}", file=sys.stderr)
        return 1

    roots = args.roots or DEFAULT_ROOTS
    # 只保留实际存在的根
    roots = [r for r in roots if (root / r).is_dir()]
    if not roots:
        print(f"[warn] 未找到任何组件目录（尝试过: {', '.join(DEFAULT_ROOTS)}），registry 将为空")
        print("[warn] 可用 --roots 显式指定项目实际的组件目录")

    stack = detect_stack(root)
    libs = stack.get("ui_libs") or ([stack["ui_library"]] if stack["ui_library"] != "unknown" else [])

    # 载入旧 registry
    old_map = {}
    out_path = Path(args.out)
    if out_path.is_file() and not args.force:
        try:
            old = json.loads(out_path.read_text(encoding="utf-8", errors="replace"))
            old_map = {c.get("path", ""): c for c in old.get("components", [])}
        except Exception:
            old_map = {}

    # 取文件列表
    files = run_git_ls_files(root)
    src_used = "git"
    if files is None:
        files = walk_files(root, roots)
        src_used = "walk"
    files = [f for f in files if f.endswith((".tsx", ".ts", ".jsx", ".js", ".vue")) and not is_excluded(f)]

    # 只保留在扫描根内的文件
    def under_roots(rel):
        return any(rel == r or rel.startswith(r.rstrip("/") + "/") for r in roots)

    if roots:
        files = [f for f in files if under_roots(f)]

    # 解析
    comps, reused = [], 0
    for rel in sorted(set(files)):
        c = build_component(root, rel, old_map.get(rel, {}), libs)
        if not c:
            continue
        if old_map.get(rel) is c:
            reused += 1
        comps.append(c)

    # 二次解析：填充对本地组件的依赖
    local_names = {c["name"] for c in comps} | {Path(c["path"]).stem for c in comps}
    for c in comps:
        try:
            text = (root / c["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        c["depends_on"] = detect_local_deps(text, local_names, c["name"])

    # 清理空字段
    for c in comps:
        for k in ("tags", "variants", "depends_on", "composes_library", "tokens_used"):
            if not c.get(k):
                c.pop(k, None)
        c.setdefault("platform", [])

    total = len(comps)
    coverage = round(reused / total, 3) if total else 1.0
    registry = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stack": stack,
        "scan": {
            "roots": roots,
            "file_source": src_used,
            "files_scanned": len(files),
            "fingerprint_coverage": coverage,
            "stale": bool(old_map) and coverage < 1.0,
        },
        "components": comps,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] 扫描 {len(files)} 个文件，识别 {total} 个组件 -> {out_path}")
    print(f"     指纹复用 {reused}/{total} (覆盖率 {coverage:.1%})，文件来源: {src_used}")
    print(f"     技术栈: {stack['framework']} / {stack['ui_library']}")
    if registry["scan"]["stale"]:
        print("[warn] 存在失配文件，registry.stale=true；据此判断组件是否存在时必须回落到实际文件确认")
    return 0


if __name__ == "__main__":
    sys.exit(main())
