# agent-skills

6iedog 的个人 Agent Skills 仓库。用 [`skills`](https://github.com/vercel-labs/skills) CLI 分发，遵循「一个 skill = 一个含 `SKILL.md` 的目录」这一约定。

## 安装

```bash
# 先看仓库里有哪些 skill（不安装）
npx skills add 6iedog/agent-skills --list

# 全部装到当前项目
npx skills add 6iedog/agent-skills

# 只装某一个
npx skills add 6iedog/agent-skills --skill component-create

# 全局安装，且只装到 Trae CN
npx skills add 6iedog/agent-skills -g -a trae-cn -y
```

| 参数 | 作用 |
|---|---|
| `-g` | 装到用户级（`~/<agent>/skills/`），所有项目可用；不加则装到当前项目 |
| `-a <agent>` | 指定 agent：`trae-cn`、`claude-code`、`cursor` 等；`'*'` 表示全部 |
| `--skill <name>` | 只装指定 skill，可重复；`'*'` 表示全部 |
| `--list` | 只列出可装的 skill，不安装 |
| `--copy` | 复制而非 symlink |
| `-y` | 跳过确认 |

## 本地开发（改完不用 push）

直接用本地路径安装即可，不需要提交或推送到 GitHub：

```bash
# 在仓库根目录运行

# 1) 预览 CLI 能扫到哪些 skill
npx skills add .\skills --list

# 2) 装到 Trae CN（全局）
npx skills add .\skills\<skill-name> -g -a trae-cn -y
```

**机制**：symlink 模式下，CLI 先把 skill 复制到 `~/.agents/skills/<name>`，再在 agent 目录（如 `~/.trae-cn/skills/<name>`）建 junction 指过去。所以**改完源码要重跑一次上面的命令**才生效。

想做到「改完即时生效」，手动建一次 junction，直接指向仓库里的 skill 目录：

```powershell
New-Item -ItemType Junction `
  -Path "$env:USERPROFILE\.trae-cn\skills\<skill-name>" `
  -Target "C:\Repository\6iedog\agent-skills\skills\<skill-name>"
```

之后编辑文件立刻生效，不用再跑 CLI。删除用 `Remove-Item <junction 路径>`（只删链接，不动源目录）。

其他有用的命令：

```bash
npx skills use .\skills\<skill-name>   # 临时试用，不安装
npx skills list -g                     # 看全局装了哪些
npx skills update -g -y                # 更新全局 skill
```

> 在仓库内测试时**务必带 `-g`**。不加 `-g` 会把 skill 装进当前目录的 `.trae/skills/`（Trae 的项目级路径），污染仓库。

## 目录结构

```
skills/
└── <skill-name>/
    ├── SKILL.md          # 必需；frontmatter 必须含 name + description
    ├── references/       # 可选：按需加载的细节文档
    ├── assets/           # 可选：模板等产出素材
    ├── scripts/          # 可选：脚本
    └── evals/            # 可选：测试用例
        └── evals.json
```

CLI 的扫描顺序是「仓库根 → `skills/` → 各 agent 目录」，`skills/` 这类容器目录会往下扫 3 层。所以 `skills/<name>/SKILL.md` 是最省事的布局。

## 现有 skill

| Skill | 作用 | 触发场景 |
|---|---|---|
| component-governance | 组件「应该怎么做」：初始化、制定/修订项目提示词集、审查存量、统一风格 | 待重写 |
| component-create | 组件「这次怎么做」：新建组件、消歧、补规格文档 | 待重写 |
| daily-brief | 每日新闻早报：说人话 + 打比方的文风，产出单文件 HTML（图文 + 内嵌逐条语音）。**领域由调用方传入**（不预设主题） | 生成早报 / 每日简报 / 行业晨报 |

## 新增一个 skill

1. 建目录 `skills/<skill-name>/`（kebab-case，与 frontmatter 的 `name` 一致）
2. 写 `SKILL.md`：

```markdown
---
name: my-skill
description: 做什么 + 什么时候该触发。description 是唯一决定触发的字段，边界要写清
---

# My Skill

决策骨架写这里，细节放 references/ 按需加载。
```

3. 用 `npx skills add .\skills --list` 确认能扫到

## 测试用例（evals）

`skills` CLI **本身不带** evals 功能（它只有 `add` / `use` / `list` / `update` / `remove` / `init` / `check`）。evals 的约定来自 Anthropic 的 [`skill-creator`](https://github.com/anthropics/skills)：

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "用户会给出的任务描述",
      "expected_output": "期望产出的说明",
      "assertions": ["可验证的事实，例如：生成文件里没有硬编码色值"]
    }
  ]
}
```

需要跑用例时可以装 `skill-creator`：

```bash
npx skills add anthropics/skills --skill skill-creator
```

## 相关

- skills CLI 源码：https://github.com/vercel-labs/skills ｜ skill 目录站：https://skills.sh
- `find-skills`：教 agent 怎么用 `npx skills find / add / check / update`
  → `npx skills add vercel-labs/skills --skill find-skills`
- `skill-creator`：写/改 skill、跑 evals
  → `npx skills add anthropics/skills --skill skill-creator`