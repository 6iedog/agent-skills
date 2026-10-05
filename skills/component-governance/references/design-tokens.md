# 设计令牌体系

## 为什么令牌比规范文档更有效

规范文档靠人读、靠人记，久了必然漂移。令牌把规范变成**代码里可被检查的值**——`check_tokens.py` 能自动发现硬编码，这是任何文字规范都做不到的。

所以原则是：**能变成令牌的规则，不要留在文档里。**

## 令牌分类与层级

```
1. 基础层 (primitive)     调色板、字号刻度、间距刻度
2. 语义层 (semantic)      语义色、角色尺寸、交互状态值
3. 组件层 (component)     单组件的特殊值（慎用）
```

**组件只允许消费语义层和组件层，不允许直接消费基础层。**

```css
/* 好 */ color: var(--color-text-secondary);
/* 坏 */ color: var(--color-gray-600);
```

理由：基础层换主题时会变，组件直接引用基础层会在换肤时失控。

## 语义令牌表（标准集合）

### 颜色

```json
{
  "color": {
    "primary":              "主色，主要操作",
    "primary-hover":        "主色悬停",
    "primary-active":       "主色按下",
    "success":              "成功",
    "warning":              "警告",
    "danger":               "危险/删除",
    "danger-hover":         "危险悬停",

    "text":                 "主文本",
    "text-secondary":       "次要文本",
    "text-tertiary":        "占位/禁用文本",
    "text-inverse":         "反色文本",

    "bg":                   "页面背景",
    "bg-container":         "容器背景",
    "bg-hover":             "悬停背景",
    "bg-active":            "选中背景",
    "bg-mask":              "遮罩背景",

    "border":               "常规边框",
    "border-strong":        "强调边框",
    "border-focus":         "聚焦边框"
  }
}
```

**必须存在的语义色**：`danger` 与 `primary` 必须视觉可区分——这是危险操作能被识别的物理基础。红绿色觉障碍用户约占男性 8%，所以危险态不能只靠颜色，还要配图标或文字（对应 `interaction-ux.md` 第 9 节）。

### 尺寸

```json
{
  "size": {
    "control-height": {
      "sm": "24px", "md": "32px", "lg": "40px"
    },
    "space": {
      "base": "4px", "xs": "8px", "sm": "12px",
      "md": "16px", "lg": "24px", "xl": "32px", "xxl": "48px"
    },
    "radius": {
      "sm": "4px", "md": "6px", "lg": "8px", "full": "9999px"
    },
    "font-size": {
      "xs": "12px", "sm": "14px", "md": "16px", "lg": "20px", "xl": "24px"
    }
  }
}
```

`space.base` 是间距基数，所有间距必须是它的整数倍。这条约束让 `check_tokens.py` 能做严格校验。

### 层级与动效

```json
{
  "z-index": { "dropdown": 1050, "modal": 1000, "tooltip": 1080, "toast": 1100 },
  "motion": {
    "duration": { "fast": "0.1s", "normal": "0.2s", "slow": "0.3s" },
    "easing": { "standard": "cubic-bezier(0.4, 0, 0.2, 1)" }
  }
}
```

**z-index 必须用令牌**，不允许出现 `z-index: 9999`。这类魔法值是弹层错乱的根源，且极难排查。

动效必须提供 `prefers-reduced-motion` 降级。

## 令牌缺失时的处理

生成组件过程中发现令牌缺项时：

1. **先看能否用已有值组合** —— 多数「缺项」其实是已有值叠加
2. 确实需要新增 → 加入 `tokens.json` 并在 `DESIGN.md` 记录
3. 新增的是基础层还是语义层？→ 组件通常只应新增语义层，基础层扩充要克制

**不要在组件里定义局部常量绕过令牌**：

```tsx
// 坏
const PADDING = 7;
// 好
padding: 'var(--space-xs)'   // 8px = base 4px × 2
```

## 令牌与规范的分工

| 类型 | 归属 | 检验方式 |
|---|---|---|
| 具体数值（圆角 6px、间距基数 4） | `tokens.json` | 脚本自动校验 |
| 使用场景（什么时候用 sm 不用 md） | `DESIGN.md` | 人工判断 |
| 交互规则（危险操作怎么确认） | `interaction-ux.md` | 检查清单 |

判断标准：**能量化的量化，量化的进令牌。** 别把"危险按钮用红色"塞进 tokens——它是规则不是值。
