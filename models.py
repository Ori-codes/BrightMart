"""Data models for the BrightMart Inventory & Sales Management System.

These classes mirror the class diagram in the technical report
(User, Supplier, Product, SaleItem and Sale).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


class ValidationError(Exception):
    """Raised when user input or a business rule is invalid.

    The message is written so that it can be shown directly to the user.
    """


@dataclass
class User:
    user_id: int
    username: str
    full_name: str
    role: str


@dataclass
class Supplier:
    supplier_id: int
    supplier_name: str
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""


@dataclass
class Product:
    product_id: int
    name: str
    category_id: Optional[int]
    supplier_id: Optional[int]
    unit_price: float
    quantity_in_stock: int
    reorder_level: int
    category_name: str = ""
    supplier_name: str = ""

    def is_low_stock(self) -> bool:
        """A product is low on stock when it is at or below its reorder level."""
        return self.quantity_in_stock <= self.reorder_level

    def reduce_stock(self, quantity: int) -> None:
        if quantity <= 0:
            raise ValidationError("Quantity must be at least 1")
        if quantity > self.quantity_in_stock:
            raise ValidationError(
                f"Insufficient stock for {self.name}. Available: {self.quantity_in_stock}")
        self.quantity_in_stock -= quantity

    def increase_stock(self, quantity: int) -> None:
        if quantity <= 0:
            raise ValidationError("Quantity must be greater than zero")
        self.quantity_in_stock += quantity


@dataclass
class SaleItem:
    product: Product
    quantity: int
    unit_price: float

    def line_total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


@dataclass
class Sale:
    user_id: int
    items: List[SaleItem] = field(default_factory=list)
    sale_id: Optional[int] = None
    sale_datetime: Optional[str] = None

    def add_item(self, product: Product, quantity: int) -> None:
        """Add a product to the sale, checking the quantity against current stock."""
        if not isinstance(quantity, int) or quantity <= 0:
            raise ValidationError("Quantity must be at least 1")
        for item in self.items:
            if item.product.product_id == product.product_id:
                if item.quantity + quantity > product.quantity_in_stock:
                    raise ValidationError(
                        f"Insufficient stock for {product.name}. "
                        f"Available: {product.quantity_in_stock}")
                item.quantity += quantity
                return
        if quantity > product.quantity_in_stock:
            raise ValidationError(
                f"Insufficient stock for {product.name}. Available: {product.quantity_in_stock}")
        self.items.append(SaleItem(product, quantity, product.unit_price))

    def remove_item(self, product_id: int) -> None:
        self.items = [i for i in self.items if i.product.product_id != product_id]

    def calculate_total(self) -> float:
        return round(sum(i.line_total() for i in self.items), 2)

    @property
    def total_amount(self) -> float:
        return self.calculate_total()
