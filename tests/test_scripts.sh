#!/usr/bin/env bash
# component-governance 脚本层测试
#
# 用法: bash scripts/test.sh [python路径]
# 默认 python3，可用第一个参数覆盖
#
# 测什么：脚本的确定性行为（检出能力 + 不误报 + 边界处理）
# 不测什么：Skill 的模型行为（触发准确性、追问质量、消歧质量）
#         —— 那部分必须在真实会话里人工验，脚本测不了

set -u
PY="${1:-python3}"
S="$(cd "$(dirname "$0")" && pwd)"
ASSETS="$(dirname "$S")/assets"

PASS=0
FAIL=0
ok()  { echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad() { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
has() { grep -q "$2" "$1" && ok "$3" || bad "$3"; }

WORK=$(mktemp -d)
PROJ="$WORK/proj"
trap 'rm -rf "$WORK"' 2>/dev/null

mkdir -p "$PROJ/src/components/BadFilter" "$PROJ/src/components/GoodFilter" \
         "$PROJ/src/components/hooks" "$PROJ/src/empty" "$PROJ/.ui-kit"

cat > "$PROJ/package.json" <<'EOF'
{ "name": "test", "dependencies": { "react": "^18.0.0", "antd": "^5.0.0" } }
EOF

# 缺陷组件：注入 7 个典型问题
cat > "$PROJ/src/components/BadFilter/index.tsx" <<'EOF'
import { Select, DatePicker, Button } from 'antd';
export const BadFilter = ({ onSearch }) => (
  <div style={{ padding: '13px', borderRadius: '7px', background: '#f0f5ff' }}>
    <Select options={[]} style={{ width: 200 }} />
    <DatePicker />
    <Button type="primary" onClick={onSearch}>查询</Button>
    <button style={{ outline: 'none' }}><i>⋯</i></button>
    <button style={{ width: 20, height: 20 }} aria-label="更多"><i>⋯</i></button>
    <div onClick={onSearch}>重置</div>
  </div>
);
EOF

# 合规组件：状态齐、变体有、可清除可取消、有 aria-label
cat > "$PROJ/src/components/GoodFilter/index.tsx" <<'EOF'
import { useState, useCallback } from 'react';
const SIZES = { sm: '24px', md: '32px' };
const RADII = { md: '6px' };
const SPACING = { md: '16px' };
export const GoodFilter = ({ onSearch }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [empty, setEmpty] = useState(false);
  const [size, setSize] = useState('md');
  const [variant, setVariant] = useState('outlined');
  const [disabled, setDisabled] = useState(false);
  const onClear = useCallback(() => {}, []);
  const onCancel = useCallback(() => {}, []);
  return (
    <div style={{ padding: SPACING.md, borderRadius: RADII.md, width: SIZES[size] }}>
      {loading && <span>加载中</span>}
      {error && <span role="alert">{error}</span>}
      {empty && <span>无数据</span>}
      <button onClick={onClear}>清除</button>
      <button onClick={onCancel}>取消</button>
      <button onClick={() => onSearch?.()} disabled={disabled} aria-label="查询">查询</button>
    </div>
  );
};
EOF

cat > "$PROJ/src/components/hooks/useFilter.ts" <<'EOF'
import { useState, useEffect } from 'react';
export const useFilter = (init) => {
  const [v, setV] = useState(init);
  useEffect(() => {}, [init]);
  return { v, setV };
};
EOF

cp "$ASSETS/design-tokens.json.tmpl" "$PROJ/.ui-kit/tokens.json"

echo "=== 1. scan_components 建索引 ==="
"$PY" "$S/scan_components.py" "$PROJ" --out "$PROJ/.ui-kit/registry.json" > "$WORK/o1" 2>&1
[ -f "$PROJ/.ui-kit/registry.json" ] && ok "registry.json 已生成" || bad "registry.json 未生成"
has "$WORK/o1" "react / antd" "识别出技术栈"

echo "=== 2. 增量重跑（指纹复用）==="
"$PY" "$S/scan_components.py" "$PROJ" --out "$PROJ/.ui-kit/registry.json" > "$WORK/o2" 2>&1
has "$WORK/o2" "100.0%" "指纹全部复用"

echo "=== 3. check_tokens 检出能力 ==="
"$PY" "$S/check_tokens.py" "$PROJ/src/components" --tokens "$PROJ/.ui-kit/tokens.json" --platform web > "$WORK/o3" 2>&1
has "$WORK/o3" "硬编码色值"      "检出硬编码色值"
has "$WORK/o3" "魔法圆角"        "检出魔法圆角"
has "$WORK/o3" "魔法内边距"      "检出魔法内边距"
has "$WORK/o3" "outline: none"   "检出 outline:none"
has "$WORK/o3" "状态覆盖可能不足" "检出状态缺失"

echo "=== 4. check_contract 检出能力 ==="
"$PY" "$S/check_contract.py" "$PROJ/src/components" --spec-dir "$PROJ/.ui-kit/catalog" > "$WORK/o4" 2>&1
has "$WORK/o4" "缺少组件规格文档"     "检出缺规格文档"
has "$WORK/o4" "可清除/反悔"          "检出缺反悔路径"
has "$WORK/o4" "取消/关闭路径"         "检出缺取消路径"
has "$WORK/o4" "outline: none"         "检出 outline:none"
has "$WORK/o4" "可点击的 div 不可聚焦"  "检出 div 不可键盘操作"
has "$WORK/o4" "缺少无障碍名称"        "检出图标按钮缺 aria-label"

echo "=== 5. 不误报（合规组件）==="
"$PY" "$S/check_contract.py" "$PROJ/src/components/GoodFilter" --no-spec > "$WORK/o5" 2>&1
has "$WORK/o5" "0 error" "合规组件 0 error"

echo "=== 6. 边界：hook 被跳过 ==="
has "$WORK/o4" "检查 1 个组件" "只检查真实组件（hook 已跳过）"

echo "=== 7. 边界：空目录 ==="
"$PY" "$S/check_contract.py" "$PROJ/src/empty" >/dev/null 2>&1
[ $? -eq 2 ] && ok "空目录退出码 2" || bad "空目录退出码应为 2"

echo "=== 8. compliance 维度汇总 ==="
"$PY" "$S/check_contract.py" "$PROJ/src/components" --spec-dir "$PROJ/.ui-kit/catalog" --format compliance > "$WORK/o8" 2>&1
has "$WORK/o8" "1-角色"   "含第 1 维"
has "$WORK/o8" "7-无障碍" "含第 7 维"

echo "=== 9. 平台阈值差异（20px 元素）==="
"$PY" "$S/check_tokens.py" "$PROJ/src/components" --tokens "$PROJ/.ui-kit/tokens.json" --platform mobile > "$WORK/o9" 2>&1
has "$WORK/o9" "44px" "mobile 判为 error（44px 阈值）"
has "$WORK/o3" "24px" "web 判为 warning（24px 阈值）"
echo "$WORK/o9" | grep -q "ERROR" && ok "mobile 下 20px 触发 error" \
  || bad "mobile 下未升级为 error"

echo ""
echo "======================================="
echo "通过 $PASS / 失败 $FAIL"
if [ "$FAIL" -eq 0 ]; then echo "结果: 全部通过"; exit 0; else echo "结果: 存在失败"; exit 1; fi
