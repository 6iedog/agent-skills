# 组件 Skill 包

> 两个独立 Skill，各自可触发，通过项目里的 `.ui-kit/` 协作。

## 为什么拆成两个

治理和创建是**两类完全不同的活动**：

| | 组件治理 | 组件创建 |
|---|---|---|
| 回答的问题 | 应该怎么做 | 这次怎么做 |
| 频率 | 低频、持续维护 | 高频、每个需求 |
| 产出物 | 规范、令牌、索引 | 组件代码、规格文档 |
| 变更时机 | 团队认知更新时 | 每次写组件 |
| 混在一起的问题 | 规范维护被日常需求淹没 | 加载一堆用不上的规范 |

**混在一起的实测代价**：写一个组件要读 7 份 references（规范、令牌、契约、消歧、追问、提示词、平台差异），其中大半与本次无关。拆开后，创建路径只需读 3 份（消歧、追问、提示词），规范由治理包产出在 `.ui-kit/` 里按需取。

## 结构

```
skills/
├── component-governance/       治理包（规范 + 审查 + 沉淀）
│   ├── SKILL.md
│   ├── references/
│   │   ├── component-design.md   七维组件契约
│   │   ├── interaction-ux.md     通用操作习惯规范
│   │   ├── design-tokens.md      设计令牌体系
│   │   ├── platform-web.md       PC 平台差异（hover/右键/快捷键/拖拽）
│   │   └── registry.md           .ui-kit/ 协议与 registry
│   ├── assets/                   3 份模板（tokens / DESIGN / conventions）
│   └── scripts/                  3 个脚本（扫描 / 令牌校验 / 契约审查）
│
└── component-create/           创建包（消歧 + 追问 + 生成）
    ├── SKILL.md
    ├── references/
    │   ├── morphology.md         形态 ↔ 数据条件判定表
    │   ├── questioning.md        八步追问 + Gate 机制
    │   ├── component-prompts.md  组件描述提示词骨架
    │   ├── routing.md            平台判定
    │   └── stack-react.md        React 适配
    └── assets/
        └── component-catalog.md.tmpl   规格文档骨架
```

## 协作方式

**两包通过项目里的 `.ui-kit/` 通信，不互相加载。**

```
component-governance 写 .ui-kit/  ──────→  component-create 读 .ui-kit/
  ├─ tokens.json      令牌数值           ├─ 生成时取值，不硬编码
  ├─ conventions.md   项目约定           ├─ 追问前读，已约定的不问
  ├─ registry.json    组件索引           ├─ 复用决策
  └─ interaction-ux   交互规范（全局）   └─ 生成时对照 Do & Don't

component-create 写 .ui-kit/catalog/  ──→  component-governance 巡检时检查
```

`.ui-kit/` 不存在 = 项目还没接入治理。此时 `component-create` 应提示用户先初始化，生成的值标注「建议值，需治理确认」。

## 调用契约

`component-create` 需要治理包的脚本（校验）：

```
1. 取自身 SKILL.md 所在目录的绝对路径
2. 向上找到包含本包的 skills/ 目录
3. 在同级查找 component-governance/
4. 校验其 contract_version 与本包一致
```

版本不一致 → **停止并告知用户**。版本错配会导致规范与校验脚本对不上。

## 两个硬约束

### 只有各自 description 写「使用时机」

两包 description 边界要清晰，否则会互相抢触发：

- **治理**：「规范/统一/审查/巡检/令牌/token/设计系统/风格不一致」
- **创建**：「写组件/加个组件/做一个筛选器/补规格文档/描述不清只说了形态词」

反面例子：治理包 description 里写「创建组件时的规范依据」→ 创建场景下两个包都会被触发，模型随机挑一个。

### 平台差异归治理包，不再单独分包

`platform-web.md` 是一份文档，不是一个包。**为它建一套包契约（谁能触发、版本对齐、降级）不值得。**

移动端差异（触控热区、安全区、手势冲突、拇指可达区）尚未收录，需要时按同格式补进治理包。

## 维护

**加规范** → 通用进 `interaction-ux.md`，项目特有进 `.ui-kit/conventions.md`。项目反对全局规范时写例外条款，不改全局文件。

**加组件类型的提问脚本** → `component-create/references/questioning.md`。

**加组件类型的提示词骨架** → `component-create/references/component-prompts.md`。

**加平台差异** → 治理包 `references/platform-*.md`，**不要**复制通用规范（发现重复说明该条目该上移）。

## 常见误区

**误区一：两包互相加载**

治理包不该在创建流程里被调用；创建包也不该维护规范。规范是**读** `.ui-kit/`，不是**读另一个包**。

**误区二：创建包自带规范副本**

会导致两边规范漂移，且改动要同步两处。规范只在治理包存在一份。

**误区三：治理包塞流程细节**

「怎么追问」「怎么生成」属于创建包。治理包只管「应该做成什么样」。

**误区四：创建包单方面改全局规范**

`component-create` 遇到令牌缺项，规范缺项，应**告知用户**让治理包补，不自己改 `interaction-ux.md`。

**误区五：以为两包必须有 contract_version 一致才能用**

不是。版本检查是**跨包调用脚本时**的保险。两个包各自独立可用，只是校验能力有强有弱。
