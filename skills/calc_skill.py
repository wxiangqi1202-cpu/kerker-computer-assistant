"""技能：计算数学表达式"""

from skills import register


def calculate(expression):
    allowed = set("0123456789+-*/.() ")
    if not all(ch in allowed for ch in expression):
        return "不支持的表达式"
    return eval(expression)


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
