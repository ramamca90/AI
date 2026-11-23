"""Custom tools that run on YOUR machine.

The agent decides when to call these. The Python client (agent_client.py)
receives the call, runs the matching function here, and sends the result back.
"""

import ast
import operator
from datetime import datetime

# ---------------------------------------------------------------------------
# Tool definitions (sent to the agent once, in setup_agent.py)
# ---------------------------------------------------------------------------

CUSTOM_TOOLS = [
    {
        "type": "custom",
        "name": "lookup_order",
        "description": (
            "Look up an order in the company order database by its order ID "
            "(e.g. 'A1001'). Returns status, item and delivery date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order ID, e.g. A1001"}
            },
            "required": ["order_id"],
        },
    },
    {
        "type": "custom",
        "name": "calculate",
        "description": "Evaluate a basic arithmetic expression such as '(12.5 * 4) / 3'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Arithmetic expression"}
            },
            "required": ["expression"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_FAKE_ORDERS = {
    "A1001": {"status": "shipped", "item": "Laptop stand", "delivery": "2026-11-26"},
    "A1002": {"status": "processing", "item": "USB-C hub", "delivery": "2026-11-30"},
    "A1003": {"status": "delivered", "item": "Mechanical keyboard", "delivery": "2026-11-20"},
}


def lookup_order(order_id: str) -> str:
    order = _FAKE_ORDERS.get(order_id.strip().upper())
    if order is None:
        return f"No order found with ID {order_id}."
    return (
        f"Order {order_id.upper()}: {order['item']} - status {order['status']}, "
        f"delivery {order['delivery']}."
    )


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("Unsupported expression")


def calculate(expression: str) -> str:
    """Safe arithmetic (no eval())."""
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except Exception as exc:  # noqa: BLE001 - report any failure back to the agent
        return f"Error: {exc}"


# Map tool name -> Python function
TOOL_HANDLERS = {
    "lookup_order": lambda args: lookup_order(args["order_id"]),
    "calculate": lambda args: calculate(args["expression"]),
}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    """Run a tool. Returns (result_text, is_error)."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}", True
    try:
        return handler(args), False
    except Exception as exc:  # noqa: BLE001
        return f"Tool {name} failed at {datetime.now():%H:%M:%S}: {exc}", True
