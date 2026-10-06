"""运行变量、文本插值与条件求值。

（模块名用 runvars 而不是 vars：`vars` 是 Python 内置函数名，同名模块会让人误读，
也容易在 `import vars` 的地方踩到意想不到的覆盖。）
《节点设计规范 V1》里「数据」类节点（变量 / 运算 / 文本处理）与「流程」类节点
（判断 / 循环 / 等待）都需要一套统一的取值与比较规则。这套规则刻意做得**很窄**：

  · 变量就是一个扁平的字符串→值 的字典，整个工作流（含子脚本）共享一份作用域。
    不做嵌套、不做类型系统 —— 挂机脚本要的是"把上一步看到的数字带到下一步"，
    而不是一门语言。
  · 文本里写 `{{name}}` 表示"插入变量 name 的值"。
  · 条件就是「左值 运算符 右值」三件套，左值优先按**变量名**解释。

安全：运算表达式用 ast 白名单求值（只允许数字、变量、四则运算与几个数学函数），
**绝不**用 eval —— 脚本文件是可能从别人那里拷来的，能执行任意代码的表达式等于后门。
"""
from __future__ import annotations

import ast
import re
from typing import Any

# {{ 变量名 }}：变量名允许中文、字母数字下划线点，两侧空格可有可无
_VAR_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

# 只认这些函数，别的名字一律拒绝
_SAFE_FUNCS: dict[str, Any] = {
    'abs': abs,
    'min': min,
    'max': max,
    'round': round,
    'int': int,
    'float': float,
    'len': len,
    'str': str,
}


class VarScope:
    """一次运行的变量表。子脚本与主脚本共用同一份（规范：变量作用域为整个工作流）。"""

    def __init__(self) -> None:
        self.vars: dict[str, Any] = {}

    def get(self, name: str, default: Any = None) -> Any:
        return self.vars.get(str(name), default)

    def set(self, name: str, value: Any) -> None:
        key = str(name or '').strip()
        if key:
            self.vars[key] = value

    def delete(self, name: str) -> None:
        self.vars.pop(str(name or '').strip(), None)

    def snapshot(self) -> dict[str, Any]:
        return dict(self.vars)


def _to_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


# 公开别名：「文本处理-转数字」等节点需要同一套解析规则，
# 不能各自实现一遍（否则 "3.5" 在 A 处能转、在 B 处转不了）
to_number = _to_number


def coerce(value: Any, var_type: str = 'auto') -> Any:
    """按声明类型把用户的文本转成真正的值。

    auto：能当数字就当数字，"yes/no/true/false" 当布尔，其余保持字符串。
    这一步很关键：否则「运算」节点拿到的是字符串 "5"，`{{a}} + 1` 会变成拼接。
    """
    v = value
    if isinstance(v, str):
        v = v.strip()
    t = str(var_type or 'auto')
    if t == 'string':
        return '' if v is None else str(v)
    if t == 'number':
        n = _to_number(v)
        return n if n is not None else 0
    if t == 'bool':
        return str(v).strip().lower() in {'yes', 'true', '1', 'on', '是', '真'}
    # auto
    if isinstance(value, (int, float, bool)):
        return value
    s = str(v)
    low = s.lower()
    if low in {'yes', 'true'}:
        return 'yes'  # 视觉节点输出的 yes/no 保持原样，便于字符串比较
    if low in {'no', 'false'}:
        return 'no'
    n = _to_number(s)
    if n is not None and s != '':
        # 整数就还原成整数，避免日志里出现 "3.0 次"
        return int(n) if float(n).is_integer() else n
    return s


def interpolate(text: Any, scope: VarScope) -> str:
    """把文本里的 {{var}} 替换成变量值（值不是字符串时转成字符串）。"""
    s = '' if text is None else str(text)

    def _sub(m: re.Match) -> str:
        val = scope.get(m.group(1))
        if val is None:
            return ''
        return str(val)

    return _VAR_RE.sub(_sub, s)


def resolve(raw: Any, scope: VarScope, var_type: str = 'auto') -> Any:
    """把参数值解析成"实际值"。

    三种情况：
      · 整串恰好是一个 {{var}} → **保留变量的原始类型**（数字还是数字）
      · 文本里含多个 {{var}}   → 插值成字符串，再按 var_type 尝试转换
      · 不含 {{}}              → 按 var_type 转换（纯数字文本会变成数字）
    """
    if not isinstance(raw, str):
        return raw
    m = _VAR_RE.fullmatch(raw.strip())
    if m:
        return scope.get(m.group(1))
    if _VAR_RE.search(raw):
        return coerce(interpolate(raw, scope), var_type)
    return coerce(raw, var_type)


def operand(raw: Any, scope: VarScope) -> Any:
    """条件里的"操作数"：优先当变量名解释，其次当字面量。

    规则（写到界面上就是"左值可以直接写变量名"）：
      1. 形如 {{x}} → 变量 x 的值
      2. 裸名字且**确实存在于变量表** → 变量值
      3. 其余 → 按字面量（数字文本转数字，否则字符串）
    """
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    m = _VAR_RE.fullmatch(s)
    if m:
        return scope.get(m.group(1))
    if s in scope.vars:
        return scope.vars[s]
    if _VAR_RE.search(s):
        return interpolate(s, scope)
    return coerce(s)


def _compare(left: Any, op: str, right: Any) -> bool:
    op = str(op or '==')
    if op in ('is_empty', 'not_empty'):
        empty = left is None or str(left) == ''
        return empty if op == 'is_empty' else not empty
    if op in ('is_true', 'is_false'):
        truthy = _truthy(left)
        return truthy if op == 'is_true' else not truthy
    if op in ('contains', 'not_contains'):
        hit = str(right) in str(left if left is not None else '')
        return hit if op == 'contains' else not hit

    ln, rn = _to_number(left), _to_number(right)
    if op == '==':
        if ln is not None and rn is not None:
            return ln == rn
        return str(left) == str(right)
    if op == '!=':
        if ln is not None and rn is not None:
            return ln != rn
        return str(left) != str(right)

    # 大小比较：能转数字就按数字，否则按字符串（支持字典序）
    if ln is not None and rn is not None:
        a, b = ln, rn
    else:
        a, b = str(left), str(right)
    if op == '>':
        return a > b
    if op == '>=':
        return a >= b
    if op == '<':
        return a < b
    if op == '<=':
        return a <= b
    return False


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip().lower()
    return s not in {'', '0', 'no', 'false', 'none', 'null', '否', '假'}


def eval_conditions(params: dict, scope: VarScope) -> bool:
    """求「判断 / 循环 / 等待-变量」的条件。

    支持两种写法，都认：
      · 标准写法：`condition` + 可选 `condition2`，用 `logic`（and/or）连接
      · 简写：直接给 `left` / `op` / `right`
    第二条件"左值留空"视为不启用 —— 界面上就是这样提示用户的。
    """
    conds = []
    c1 = params.get('condition')
    if isinstance(c1, dict) and str(c1.get('left', '')).strip() != '':
        conds.append(c1)
    c2 = params.get('condition2')
    if isinstance(c2, dict) and str(c2.get('left', '')).strip() != '':
        conds.append(c2)
    if not conds and params.get('left') is not None:
        conds.append({'left': params.get('left'), 'op': params.get('op'), 'right': params.get('right')})
    if not conds:
        return False

    logic = str(params.get('logic') or 'and').lower()
    results = [
        _compare(operand(c.get('left'), scope), str(c.get('op') or '=='), operand(c.get('right'), scope))
        for c in conds
    ]
    return any(results) if logic == 'or' else all(results)


# ---------------------------------------------------------------------------
# 运算表达式（白名单求值）
# ---------------------------------------------------------------------------

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Call, ast.Compare, ast.Gt, ast.GtE, ast.Lt, ast.LtE,
    ast.Eq, ast.NotEq,
)


class ExprError(ValueError):
    pass


def _eval_node(node: ast.AST, scope: VarScope) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, scope)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)):
            return node.value
        raise ExprError('不支持的常量类型')
    if isinstance(node, ast.Name):
        if node.id in scope.vars:
            v = scope.vars[node.id]
            n = _to_number(v)
            return n if n is not None else v
        if node.id in _SAFE_FUNCS:
            return _SAFE_FUNCS[node.id]
        raise ExprError(f'未知的名字「{node.id}」（变量不存在，也不是允许的函数）')
    if isinstance(node, ast.UnaryOp):
        v = _eval_node(node.operand, scope)
        if isinstance(node.op, ast.USub):
            return -float(v)
        if isinstance(node.op, ast.UAdd):
            return float(v)
        raise ExprError('不支持的一元运算符')
    if isinstance(node, ast.BinOp):
        a = float(_eval_node(node.left, scope))
        b = float(_eval_node(node.right, scope))
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, (ast.Div, ast.FloorDiv)):
            if b == 0:
                raise ExprError('除数为 0')
            return a / b if isinstance(node.op, ast.Div) else a // b
        if isinstance(node.op, ast.Mod):
            if b == 0:
                raise ExprError('取余的除数为 0')
            return a % b
        if isinstance(node.op, ast.Pow):
            return a ** b
        raise ExprError('不支持的运算符')
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, scope)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, scope)
            ln, rn = _to_number(left), _to_number(right)
            a, b = (ln, rn) if (ln is not None and rn is not None) else (str(left), str(right))
            if isinstance(op, ast.Gt):
                ok = a > b
            elif isinstance(op, ast.GtE):
                ok = a >= b
            elif isinstance(op, ast.Lt):
                ok = a < b
            elif isinstance(op, ast.LtE):
                ok = a <= b
            elif isinstance(op, ast.Eq):
                ok = a == b
            elif isinstance(op, ast.NotEq):
                ok = a != b
            else:
                raise ExprError('不支持的比较运算符')
            if not ok:
                return 0
            left = right
        return 1
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCS:
            raise ExprError('只允许调用 abs / min / max / round / int / float / len / str')
        args = [_eval_node(a, scope) for a in node.args]
        try:
            return _SAFE_FUNCS[node.func.id](*args)
        except Exception as e:
            raise ExprError(f'函数调用失败：{e}')
    raise ExprError('表达式里含有不允许的写法')


def eval_expr(expr: str, scope: VarScope) -> float:
    """求值一个运算表达式，返回数字。表达式里的 {{var}} 会先替换成裸变量名。"""
    text = interpolate(expr, scope).strip()
    if not text:
        raise ExprError('表达式为空')
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError as e:
        raise ExprError(f'表达式语法错误：{e.msg}')
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExprError(f'表达式里不允许出现 {type(node).__name__}')
    try:
        value = _eval_node(tree, scope)
    except ZeroDivisionError:
        raise ExprError('除数为 0')
    n = _to_number(value)
    if n is None:
        raise ExprError(f'表达式的结果不是数字：{value!r}')
    return n
