# app/stock/validators.py — règles métier pour la hiérarchie des stocks
from typing import Optional
from ..models import StockNode, NodeType

MAX_LEVEL = 5

def ensure_level_valid(level: int):
    if level < 0 or level > MAX_LEVEL:
        raise ValueError(f"level must be between 0 and {MAX_LEVEL}")

def ensure_item_quantity(type_: NodeType, quantity: Optional[int]):
    if type_ == NodeType.ITEM:
        if quantity is None or quantity < 0:
            raise ValueError("quantity is required for ITEM and must be >= 0")
    else:
        if quantity is not None:
            raise ValueError("quantity must be null for GROUP")

def compute_new_level(parent: Optional[StockNode]) -> int:
    return 0 if parent is None else (parent.level + 1)

def ensure_can_add_child(parent: Optional[StockNode]):
    if parent is None:
        return
    if parent.level >= MAX_LEVEL:
        raise ValueError(f"Cannot add child: parent at max level {MAX_LEVEL}")
