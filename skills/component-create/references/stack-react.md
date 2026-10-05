# React 技术栈适配

> 适用于 React 项目。Vue 项目见 `stack-vue.md`（按需增补）。
> **UI 库细节不在本文件** —— 那属于 core 的 `.ui-kit/lib/` 能力缓存，换库就失效。

## 组件 API 设计

### Props 约定

```tsx
// 受控 + 非受控成对提供，避免调用方被迫二选一
interface Props {
  value?: T | null;
  defaultValue?: T | null;
  onChange?: (value: T | null, option: Option) => void;
}
```

- `value` / `defaultValue` 至少提供一个
- `onChange` 第二个参数带上 `option`，省去调用方反查
- 布尔属性用 `disabled` 而非 `isDisabled`（与 HTML 惯例一致）
- 事件 prop 用 `onXxx` 命名，不用 `handleXxx`

### 组合式 API

组件需要被二次封装时，暴露子组件：

```tsx
<Select
  value={v}
  onChange={setV}
  popupRender={(origin) => <MyPanel data={data}>{origin}</MyPanel>}
/>
```

比 `<Select>{(v) => ...}</Select>` 的 render props 风格更易组合，且不影响原有 API。

**判断是否暴露**：业务侧出现 2 次以上相同的包裹结构，就该提取。提前设计 headless API 会锁死组件设计。

## Hooks 规范

### forwardRef 必需的时机

组件内部有 `useState` / `useRef` / 列表 DOM 时**必须** `forwardRef`，否则调用方无法聚焦或测量：

```tsx
const Select = forwardRef<HTMLDivElement, SelectProps>((props, ref) => { ... });
Select.displayName = 'Select';   // 必须设置，否则 DevTools 显示为 Anonymous
```

`displayName` 一定要设——它影响调试体验与错误栈可读性。

### 受控值同步陷阱

**不要用 `useEffect` 同步 props 到 state**。这会引入一帧延迟并可能导致闪烁。

```tsx
// 错误：双数据源
const [inner, setInner] = useState(defaultValue);
useEffect(() => setInner(value), [value]);

// 正确：由 value 是否为 undefined 决定数据源
const isControlled = value !== undefined;
const innerValue = isControlled ? value : inner;
const merged = useMergedState(defaultValue, { value });
```

需要本地修改但由外部控制时，用 `useMergedState` 这类合并态工具，不要手写 effect 同步。

### 状态合并模式

组件同时持有内部状态和外部受控状态时（如弹层开合），统一用一个合并函数处理：

```tsx
const [open, setOpen] = useMergedState(false, { value: props.open, onChange: onOpenChange });
```

**所有受控/非受控切换都走这一个路径**，不要散落在各处 `if`。

### 副作用边界

- 事件监听、`ResizeObserver`、定时器必须在 `useEffect` cleanup 中释放
- 涉及外部数据订阅时注意 stale closure，用 `useRef` 存最新值或 `useEffectEvent`
- SSR 场景禁止直接访问 `window`/`document`，放进 `useEffect`（它只在客户端执行）

## 组合式 Hook 提取

组件逻辑复杂时提取 hook，保持组件本体为渲染层：

```
components/DataTable/
├── index.tsx           渲染层
├── useTableState.ts    排序/筛选/分页状态
├── useColumns.ts       列配置与显隐
├── types.ts            类型定义
└── __tests__/
```

**提取标准**：逻辑超过 100 行，或同一份状态逻辑在两个组件里重复出现。

类型定义独立成文件，便于消费者 `import type`。

## 项目内组件索引

React 没有内置的组件文档机制，靠约定补齐：

| 项 | 约定 |
|---|---|
| 类型导出 | 从 `types.ts` 统一导出，不用 `export type { Props } from './index'` |
| ref 类型 | `ComponentRef` 命名（`SelectRef`），调用方不用手写 `HTMLDivElement` |
| displayName | 所有组件必须设置 |
| 组件文件 | 一个组件一个文件，目录 `components/<Name>/` |

## 样式方案对接

无论用哪种方案，令牌引用要统一。

### CSS Modules

```tsx
import s from './index.module.css';
<div className={s.root} />
```

令牌用 CSS 变量：`padding: var(--size-space-md)`。`check_tokens.py` 的 `var(--…)` 白名单可直接识别。

### Tailwind

```tsx
<div className="rounded-md px-4 py-2 bg-container" />
```

把 `tailwind.config` 的 theme 映射到令牌值，**不要在类名里写任意数值**（`p-[7px]` 会被校验判为魔法值）。

### styled-components / emotion

```tsx
const Box = styled.div`padding: ${({ theme }) => theme.space.md};`;
```

主题对象即令牌源，校验时需把主题属性名加入白名单。

## 常见问题

| 问题 | 原因 | 处理 |
|---|---|---|
| 弹层被裁剪 | 父级 `overflow: hidden` | `getPopupContainer` 指定挂载节点 |
| 组件重渲染过多 | 内联对象/函数传给 memo 子组件 | `useCallback` / `useMemo`，或把函数提到组件外 |
| 焦点丢失 | 列表删除后焦点落到 body | 手动移焦点到相邻项 |
| 无限循环 | effect 依赖了每次渲染新建的对象 | 依赖用原始值或 `useRef` |
| ref 转发失效 | 忘了 `forwardRef` / 忘了设 `displayName` | 检查组件内部是否用了 hooks |

## 检查清单

- [ ] Props 契约完整，默认值全部写实
- [ ] `value`/`defaultValue` 成对，`onChange` 带 option
- [ ] `forwardRef` + `displayName` 已设置
- [ ] 受控/非受控用合并态，不靠 effect 同步
- [ ] 副作用有 cleanup
- [ ] 类型从统一入口导出
- [ ] 样式令牌引用与项目方案一致，无任意数值
- [ ] memo 场景下 props 稳定
