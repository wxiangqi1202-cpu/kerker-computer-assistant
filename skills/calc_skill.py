"""技能：计算数学表达式（安全沙箱）"""

import ast
import operator
from skills import register

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    """递归求值 AST 节点，只允许数字和基本算术运算"""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        op_func = _SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and right > 1000:
            raise ValueError("指数过大")
        return op_func(left, right)
    if isinstance(node, ast.UnaryOp):
        op_func = _SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        return op_func(_safe_eval(node.operand))
    raise ValueError(f"不支持的表达式: {ast.dump(node)}")


def calculate(expression):
    try:
        tree = ast.parse(expression, mode="eval")
        return _safe_eval(tree)
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as err:
        return f"计算错误: {err}"


register(
    name="calculate",
    description="计算数学表达式，如 3.14*2 或 (1+2)*3",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的数学表达式",
            }
        },
        "required": ["expression"],
    },
    func=calculate,
)
