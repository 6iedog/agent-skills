# AGENTS.md

给在本仓库里干活的 agent 的约定。面向人的说明见 [README.md](./README.md)，需求见 [REQUIREMENTS.md](./REQUIREMENTS.md)。

## 这是什么仓库

6iedog 的个人 Agent Skills 仓库，用 `npx skills`（[vercel-labs/skills](https://github.com/vercel-labs/skills)）分发。每个 skill 是一份给模型读的指令集。

## 硬性约定

1. **目录即 skill**：`skills/<skill-name>/SKILL.md`，目录名用 kebab-case 且与 frontmatter 的 `name` 一致。
2. **frontmatter 必须有 `name` 和 `description`**，缺一个 CLI 会直接跳过该 skill（`description` 是唯一决定触发的字段，要写清「做什么 + 何时用 + 不用它做什么」）。
3. **不做包管理**：不需要 `package.json`、不需要 npm publish、不需要任何 manifest，CLI 直接扫 `SKILL.md`。
4. **`SKILL.md` 保持精简**，控制在 250 行以内；细节放 `references/` 按需加载。超长会导致模型跳步漏读。
5. **skill 之间不能 import/include**。需要跨包引用时只能显式 `Read`，且必须先探测 `skills/` 目录的实际位置（安装位置可能是项目级或用户级），找不到要有降级路径。
6. **不要抓取具体组件库的文档**来生成通用内容。抓取器必然绑死一个库，换库即失效。

## 改完怎么验证

```bash
npx skills add ./skills --list            # 确认 CLI 能扫到、没被跳过
npx skills add ./skills/<name> -g -a trae-cn -y   # 装到本机 Trae CN 实测
```

> 路径**必须用正斜杠**：`.\skills` 会被 CLI 当成 git 仓库地址，报 `Failed to clone`。

不要基于「我以为成功了」汇报完成，要用实际命令确认。

## 测试用例（evals）

evals 不是 `skills` CLI 的功能，约定来自 Anthropic 的 `skill-creator`：用例写在 `skills/<name>/evals/evals.json`。

- 断言必须是**可验证的事实**（出现/未出现某词、数量、文件内容），不要断言精确措辞
- 三类用例要齐：`core` / `edge` / `should_not_trigger`
- 只验过程不够，断言必须包含对**生成产物**的检查
- 有配对基线意识：加载 skill 与不加载 skill 各跑一次，差值才是这个 skill 的贡献

## 协作约束（用户明确要求，硬性）

1. **不要未经允许操作 git**：不提交、不删 `.git`、不擅自恢复被删文件。
2. **不可逆操作前先问**：「删提交」「删仓库」「删文件」是三件事，不能互相替代。
3. **动手前先查有没有现成规范**：测试有 eval 标准、skill 有 authoring best practices，不要自己造。
4. **发现方向错了直接说**，不要为了维护已有工作而找理由。
5. **需求文档只描述「要什么」**，不写设计说明、演进历史、失败史（会污染下一个会话的独立判断）。