---
name: component-governance
description: 在需要建立或维护项目级组件规范时使用：初始化设计令牌、制定交互规范、定义组件设计契约、审查已有组件是否符合规范、统一多处的写法。涉及「组件规范/设计规范/统一风格/审查组件/巡检/令牌/token/设计系统/规范不一致」等诉求时使用。只管「应该怎么做」，不管「具体怎么创建」——创建用 component-create。
contract_version: 1
agent_created: true
---

# component-governance — 组件治理

## 职责边界

**管「应该怎么做」，不管「具体怎么创建」。**

| 属于本包 | 不属于本包 |
|---|---|
| 项目级规范的建立与维护 | 形态消歧、追问、生成组件代码 |
| 设计令牌（颜色/尺寸/圆角/间距/层级/动效） | 判断该用哪种组件形态 |
| 交互习惯规范（危险操作/表单/加载/空状态…） | 逐个组件的 Props 契约 |
| 组件设计契约（七维） | 组件规格文档的填写 |
| 审查已有组件是否合规 | 平台的 hover/触控热区等交互差异 |
| 项目产出物 `.ui-kit/` 的初始化与维护 | |

**要写一个新组件 → 用 `component-create`。**

拆分理由：治理是**长期、低频、需要维护**的事（规范会随团队认知更新）；创建是**日常、高频**的事。混在一起会导致规范维护被日常需求淹没。

## 什么时候用

| 场景 | 动作 |
|---|---|
| 新项目/新仓库首次接入 | 初始化 `.ui-kit/`（见下） |
| 「组件风格不统一」 | 制定令牌 + 规范，然后巡检存量 |
| 「审查一下现有组件」 | 跑 `check_contract.py` + `check_tokens.py` |
| 「这个规范怎么定」 | 补 `interaction-ux.md` 或 `conventions.md` |
| 令牌要调整 | 改 `tokens.json`，跑脚本确认影响面 |
| 团队规范要沉淀 | 写进 `conventions.md`，不写进全局规范 |

## 核心原则

### 源码是唯一真相，registry 只是索引

`.ui-kit/registry.json` 由脚本生成，可能因文件新增/改名而失真。失真不会导致错误结论，最坏情况是多扫一次。

**绝不能因为 registry 里没有就断定组件不存在** —— 必须回落到实际文件确认。

### 能推断的绝不问

规范能靠代码推断就别问用户。项目已有组件怎么写的，就是最可靠的规范依据。

### 规范与项目事实分离

| 内容 | 写在哪 | 为什么 |
|---|---|---|
| 通用最佳实践 | `references/interaction-ux.md` | 对所有项目成立 |
| 本项目约定 | `.ui-kit/conventions.md` | 只对本项目成立 |
| 通用默认（可被项目覆盖） | `references/platform-web.md` | 平台差异，PC 特有 |

**项目反对全局规范时，写进 `conventions.md` 的例外条款，不改全局文件。** 混在一起两边都不准。

### 确定性交给脚本

扫描、校验用脚本；判断规范是否合理用模型。

## 组件设计契约（七维）

任何组件都应能按这七维说清，缺哪维 AI 就只能靠猜。完整说明见 `references/component-design.md`。

```
1 角色      解决什么问题 + 不解决什么    → 决定「何时不该用」
2 数据契约  形状/量级/可否自造/变更频率 → 决定形态分支
3 交互契约  含反悔与取消路径            → 决定状态流转
4 状态全枚举 12 态，disabled ≠ readonly  → 决定会不会漏状态
5 边界与代价 「到 Y 程度会 Z」          → 决定会不会造出烂体验
6 变体轴    variant/size 等            → 决定能否复用而非复制
7 无障碍    键盘/焦点/读屏              → 决定能不能用
```

**第 1/3/5 维机器判断不了** —— 角色边界、反悔路径、边界代价只能靠人写进规格文档。`check_contract.py` 只能检查「写没写」，检查不了「写得对不对」。

## 初始化

项目根没有 `.ui-kit/` 时初始化一次。**技术栈问题一次问清**，不要分多轮：

| 问题 | 选项 | 影响 |
|---|---|---|
| 框架 | React / Vue | 组件代码风格（记录在 conventions） |
| 组件库 | 项目用哪个 / 是否自研 | 组件能力边界从哪查 |
| 组件目录 | 默认 `src/components` | 扫描范围 |
| 样式方案 | CSS Modules / Tailwind / styled-components | 令牌引用方式 |
| 已有设计令牌 | 有（给路径）/ 无 | 是否需要初始化 tokens |

步骤：

1. 从 `assets/design-tokens.json.tmpl` 生成 `.ui-kit/tokens.json`，按回答填实际值
2. 从 `assets/design-doc.md.tmpl` 生成 `.ui-kit/DESIGN.md`（令牌的人类可读版 + 使用场景）
3. 从 `assets/conventions.md.tmpl` 生成 `.ui-kit/conventions.md`
4. 生成 `.ui-kit/.gitignore`（自我保护）
5. 项目根 `.gitignore` 追加 `.ui-kit/`
6. 跑 `scripts/scan_components.py` 建首个 registry

**已有设计令牌的项目不要覆盖** —— 读入并转换结构，记在 `conventions.md` 里说明映射关系。
## 巡检存量组件

脚本在本包内，路径以本 `SKILL.md` 所在目录为基准：

```bash
# 1. 建/更新索引
python3 scripts/scan_components.py <项目根> --out <项目根>/.ui-kit/registry.json

# 2. 令牌一致性 + a11y 基础项
python3 scripts/check_tokens.py <项目根>/src/components --tokens <项目根>/.ui-kit/tokens.json --platform web

# 3. 七维契约审查（--format compliance 看维度覆盖汇总）
python3 scripts/check_contract.py <项目根>/src/components --spec-dir <项目根>/.ui-kit/catalog --format compliance
```

`--format compliance` 输出七维覆盖汇总，适合批量体检。

### 巡检结果的处置顺序

```
1. error 级（硬编码色值、outline:none、可点击 div）  → 当场修
2. 缺状态（契约第 4 维）                              → 补实现或补规格说明
3. 缺边界（契约第 5 维）                              → 人工补，这是机器补不上的
4. 缺规格文档                                        → 补 catalog，或确认该组件不需要
```

**不要一次性全量改。** 存量组件的规范问题应该是「改到哪个算哪个」，而不是专项大重构。优先级：新代码 > 高频组件 > 存量长尾。

## 维护规范

### 加一条规范

写进 `references/interaction-ux.md`（通用）或 `.ui-kit/conventions.md`（本项目）。

**每条规范要能被检查**，否则只是一句口号：

```
❌ 「按钮要美观」
✅ 「确认弹窗按钮顺序为『取消在左、确定在右』，危险操作确定按钮用危险色」
   → 可检查：截图对比 / 人工巡检
```

### 规范要写「为什么」

只写「做什么」不写「为什么」，后来者会绕过。**「为什么」是防止被误删的关键。**

```
✅ 「多选必须设上限。无上限时几十个标签会把控件撑爆变形，
    且用户无法知道自己还能选多少。」
```

### 令牌调整的流程

```
1. 改 .ui-kit/tokens.json
2. 同步改 .ui-kit/DESIGN.md 的对应表格
3. 跑 check_tokens.py 确认没有组件受影响
4. 记进 logs/decisions.mdl
```

**不要在组件里定义局部常量绕过令牌** —— 令牌体系一旦被绕过就失效了。

## 平台差异

`references/platform-web.md` 收录 PC 特有交互（hover 态、focus-visible、右键菜单、快捷键、拖拽、鼠标精度目标）。

**冲突时的优先级**：平台差异 > 通用规范。PC 有 hover、有精确光标，这是平台事实。

移动端差异（触控热区、安全区、手势冲突、拇指可达区）尚未收录，需要时按同一格式补充。

## 资源索引

| 文件 | 何时读 |
|---|---|
| `references/component-design.md` | 制定规范、判断组件是否合规 |
| `references/interaction-ux.md` | 制定/修订交互规范 |
| `references/design-tokens.md` | 初始化或调整令牌体系 |
| `references/platform-web.md` | 处理 PC 特有交互问题 |
| `references/registry.md` | 初始化 `.ui-kit/`、扩展 registry 结构 |

| 资产 | 用途 |
|---|---|
| `assets/design-tokens.json.tmpl` | 令牌骨架 |
| `assets/design-doc.md.tmpl` | DESIGN.md 骨架 |
| `assets/conventions.md.tmpl` | 项目约定骨架 |

| 脚本 | 用途 |
|---|---|
| `scripts/scan_components.py` | 扫描项目组件 → registry（带指纹增量） |
| `scripts/check_tokens.py` | 硬校验令牌一致性与 a11y 基础项 |
| `scripts/check_contract.py` | 按七维契约审查组件 |

## 与 component-create 的关系

```
component-governance                component-create
  ├─ 规范（应该怎么做）  ────────→  生成时遵循
  ├─ 令牌（具体数值）    ────────→  引用，不硬编码
  ├─ 契约（七维）        ────────→  按契约描述组件
  └─ .ui-kit/ 产出物     ────────→  读规范 + 写 catalog
```

**两包通过 `.ui-kit/` 协作，不互相加载。** `component-create` 读治理包产出的规范文件；若 `.ui-kit/` 不存在，说明项目还没接入治理，应提示用户先初始化。

## 兜底

`component-create` 不可用时（本包存在但创建包缺失），仍应做到：

1. 复用优先 —— 指出项目里已有的同类组件
2. 追问不超 2 轮，聚焦会导致返工的阻断项
3. 明确告知「未加载完整规范库，以下为通用实践建议」
4. **不要凭印象编造**具体规范条目或组件库 API

## 自我校验（改动本包后）

规范口径是否还准确，用 `evals/` 里的用例验证：

```bash
python evals/check_eval.py . --list                    # 列出用例与断言
python evals/check_eval.py . --output 回答.md --case 2  # 检查实际回答
```

**两个用例专门验证「不该触发时有没有触发」**（用例 5 会被创建类需求误触发，用例 6 会被纯实现需求误触发）。治理包最大的风险是被日常需求误触发 —— 规范维护是低频事，被高频需求卷进来就失去意义了。

断言是可验证的事实，不是主观描述，所以不同模型写法不同也判过。
