import ast
import math
import operator

OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def calculator(expression: str) -> dict:
    """Evaluate bounded numeric AST nodes; never use eval or imports."""
    if len(expression) > 500:
        raise ValueError("Expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError):
        raise ValueError("Invalid arithmetic expression") from None
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError("Expression is too complex")

    def bounded(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Only numeric constants are allowed")
        if isinstance(value, int) and value.bit_length() > 1024:
            raise ValueError("Number is too large")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Result must be finite")
        return value

    def evaluate(node):
        if isinstance(node, ast.Constant):
            return bounded(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return bounded(value if isinstance(node.op, ast.UAdd) else -value)
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent is too large")
            return bounded(OPERATORS[type(node.op)](left, right))
        raise ValueError("Only arithmetic operations are allowed")

    try:
        return {"result": evaluate(tree.body)}
    except (ArithmeticError, RecursionError):
        raise ValueError("Invalid arithmetic operation") from None
