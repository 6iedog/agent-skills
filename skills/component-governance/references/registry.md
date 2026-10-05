# registry 协议与 `.ui-kit/` 初始化

## 目录结构

```
<项目根>/
├── .gitignore              # 追加 .ui-kit/
└── .ui-kit/                # 全部产出物，被 git 忽略
    ├── .gitignore          # 自我保护
    ├── registry.json       # 组件索引（含指纹）
    ├── tokens.json         # 机器可读令牌
    ├── DESIGN.md           # 令牌的人类可读版 + 使用场景
    ├── conventions.md      # 项目级约定与例外条款
    ├── catalog/
    │   └── <Component>.md  # 单组件完整规格（模板 assets/component-catalog.md.tmpl，
    │                       #   第 1 节固定为形态消歧记录）
    ├── logs/
        └── decisions.mdl   # 决策日志（JSONL）
```

## registry.json 结构

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-04T18:00:00Z",
  "stack": { "framework": "react", "ui_library": "antd" },
  "scan": {
    "roots": ["src/components", "src/ui"],
    "fingerprint_coverage": 0.98,
    "stale": false
  },
  "components": [
    {
      "name": "DataFilterBar",
      "path": "src/components/DataFilterBar/index.tsx",
      "type": "composite",
      "exports": { "DataFilterBar": "named" },
      "depends_on": ["Select", "DatePicker", "Button"],
      "composes_library": ["antd:Select", "antd:DatePicker"],
      "tags": ["筛选", "表单", "列表页"],
      "variants": ["compact", "default"],
      "platform": ["web"],
      "capability_summary": "列表页筛选容器，聚合多条件，支持展开/收起",
      "spec": "catalog/DataFilterBar.md",
      "tokens_used": ["space.md", "radius.md", "color.text"],
      "fingerprint": { "mtime": 1759588800, "size": 4820, "hash": "a3f1" }
    }
  ]
}
```

### 关键字段

| 字段 | 作用 |
|---|---|
| `scan.fingerprint_coverage` | 指纹覆盖率。< 1 说明部分文件未经验证 |
| `scan.stale` | 索引是否可能失真。为 `true` 时**必须**回落到实际扫描确认 |
| `capability_summary` | **最重要字段**。选型时靠它判断能不能覆盖需求 |
| `tags` | 中文语义标签。用户说"筛选条"要能匹配到 `DataFilterBar` |
| `depends_on` | 依赖的自定义组件。用于判断改动影响面 |
| `composes_library` | 组合了哪些库组件。用于判断能否直接用库替代 |
| `platform` | 适用平台。跨端共用同一份 spec 时在此标注 |
| `fingerprint` | 增量扫描依据 |

### 硬规则

**registry 里没有 ≠ 组件不存在。**

`registry.json` 是索引不是真相。命中失败时必须回落到实际文件扫描确认——尤其在以下情况：

- `scan.stale === true`
- `fingerprint_coverage < 1`
- 用户说的组件名与 `name` 字段不完全一致（应同时搜中文 `tags`）
- 项目有 `registry.json` 之外的组件目录约定

## 查询协议

按顺序尝试，任一步命中即停：

```
1. 精确匹配 components[].name
2. 模糊匹配 components[].name（大小写/前缀/驼峰↔连字符）
3. 中文语义匹配 components[].tags
4. 组合词匹配 capability_summary（关键词：筛选/弹窗/列表/选择…）
5. 查项目所用组件库的官方文档（确认能力边界）
6. 全量文件扫描（registry 不可信时的兜底）
```

第 4 步做关键词匹配时，用户可能用完全不同的词描述同一组件（说"筛选器"实际叫 `DataFilterBar`），所以要按业务语义扩展关键词，不要只做字面匹配。

## 扫描

```bash
python3 scripts/scan_components.py <项目根> --out <项目根>/.ui-kit/registry.json
```

行为：
- 优先用 `git ls-files` 取文件列表（比递归快一个数量级），失败回落 `os.walk`
- 命中指纹的文件只更新索引，不重读内容
- 失配文件重新解析
- 非 `git` 项目自动回落 `os.walk`
- 扫描范围：`scan.roots` 白名单 + `package.json` 中声明的 UI 库
- 明确排除：测试文件、`.stories.`、`.d.ts`、`node_modules`、`dist`、`.ui-kit` 自身

## 首次初始化

`.ui-kit/` 不存在时初始化一次。技术栈问题**一次问清**，不要分多轮：

| 问题 | 选项 | 影响 |
|---|---|---|
| 框架 | React / Vue | 组件代码风格、Props 写法 |
| 组件库 | 项目用哪个 / 是否自研 | 决定组件能力边界从哪查 |
| 组件目录约定 | 默认 `src/components` | 扫描范围 |
| 样式方案 | CSS Modules / Tailwind / styled-components / Less | token 引用方式 |
| 是否已有设计令牌 | 有（给路径）/ 无 | 是否需要初始化 tokens.json |

初始化步骤：

1. 从 `assets/design-tokens.json.tmpl` 生成 `tokens.json`，按回答填充实际值
2. 从 `assets/conventions.md.tmpl` 生成 `conventions.md`
3. 从 `assets/design-doc.md.tmpl` 生成 `DESIGN.md`（项目级设计令牌文档：令牌值 + 何时用哪个）
4. 生成 `.ui-kit/.gitignore`
5. 在项目根 `.gitignore` 追加 `.ui-kit/`
6. 运行 `scan_components.py` 建首个 registry
7. 记录项目使用的组件库与版本到 `conventions.md`

已有设计令牌的项目**不要覆盖**，直接读入并转换到 `tokens.json` 结构。

## .gitignore 策略

项目根 `.gitignore`：

```gitignore
# 组件治理产出物
.ui-kit/
```

`.ui-kit/.gitignore`（自我保护，防止外层规则被误删）：

```gitignore
*
# 如需团队共享设计规范，取消下面任一行的注释：
# !tokens.json
# !DESIGN.md
# !catalog/
!.gitignore
```

**默认全忽略。** 组件库产出物会带来大量 diff 噪音，是否共享由用户决定。

## 组件库信息（记录而非抓取）

本 Skill **不抓取组件库文档** —— 方法论是通用的，不绑定任何库。

组件库相关的事实由两处承载：

| 记什么 | 记在哪 | 怎么更新 |
|---|---|---|
| 项目用哪个库、什么版本 | `conventions.md` | 换库时手工更新 |
| 项目封了哪些库组件 | `registry.json` 的 `composes_library` | 跑 `scan_components.py` 自动 |
| 某组件的库能力边界 | `.ui-kit/catalog/<Component>.md` | 查该项目所用库的官方文档后填 |

**为什么不自动抓取**：组件库文档的站点结构、命名、分类各不相同，
抓取器会绑死在一个库上；换个库（Element Plus / shadcn / 自研）就失效。

**需要查库能力边界时**：读项目 `package.json` 确定用的是哪个库，
查它的官方文档，把结论填进 catalog 规格文档。**不要凭印象编造库的 API。**

## 组件库无关的契约审查

```bash
python3 scripts/check_contract.py src/components --spec-dir .ui-kit/catalog
```

按 `references/component-design.md` 的七维契约审查：

| 维度 | 源码能查？ | 怎么查 |
|---|---|---|
| 1 角色（不解决什么） | 否 | 规格文档是否写明 |
| 2 数据契约 | 部分 | 规格文档 |
| 3 交互契约（反悔/取消） | 部分 | 源码搜 `onClear`/`onCancel` 等 + 规格文档 |
| 4 状态全枚举 | 是 | 源码搜状态标识 |
| 5 边界与代价 | 否 | 规格文档是否写「到 Y 程度会 Z」 |
| 6 变体轴 | 是 | 源码搜 `variant`/`size` |
| 7 无障碍 | 是 | 源码搜 `outline`/`aria-label`/可点击 div |

`--format compliance` 输出七维覆盖汇总，用于批量体检。


## 决策日志

`logs/decisions.mdl` 记录关键决策，每行一个 JSON：

```json
{"ts":"2026-10-04T18:00:00Z","type":"component_created","name":"DataFilterBar","reason":"组件库无筛选容器","answers":{"scene":"列表页筛选区","data":"接口全量<200","model":"多条件组合"},"tokens_added":["space.md"]}
{"ts":"2026-10-04T18:20:00Z","type":"convention_added","text":"列表页筛选统一用 DataFilterBar，不新建","scope":"project"}
{"ts":"2026-10-04T18:30:00Z","type":"exception","text":"本项目允许在 Tooltip 内放链接（因内容仅展示类）","against":"interaction-ux.md #4"}
```

用途：回溯「当初为什么这么定」。组件被改坏时能查到引入原因，避免反复摇摆。

## 沉淀的晋升机制

`conventions.md` 的条目累积到一定量后，自动成为追问的默认值来源：

```
conventions.md 有「列表页筛选统一用 DataFilterBar」
    ↓
下次需求涉及筛选 → 命中「可推断」→ 直接用，不问
```

**这是"下次复用"的真正落地机制。** 没有晋升，conventions.md 只是一份没人看的文档。

判断是否晋升：同类约定出现 2 次以上，或用户明确说过「以后都用 X」。晋升后该项成为 G1（不问），并可反哺 `tokens.json`（若约定含具体数值）。
