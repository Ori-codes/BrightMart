"""Inventory and supplier management (CRUD, search, low-stock, receiving stock)."""
import sqlite3
from datetime import datetime
from typing import List, Optional

from database import DATE_FORMAT, DatabaseManager
from models import Product, Supplier, ValidationError


# ---------- input validation helpers ----------
def _text(value, label: str, required: bool = True) -> str:
    value = (value or "").strip()
    if required and not value:
        raise ValidationError(f"{label} is required")
    return value


def _whole_number(value, label: str, minimum: int = 0) -> int:
    try:
        number = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValidationError(f"{label} must be a whole number")
    if number < minimum:
        raise ValidationError(f"{label} must be at least {minimum}")
    return number


def _price(value) -> float:
    try:
        number = float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        raise ValidationError("Price must be a number")
    if number <= 0:
        raise ValidationError("Price must be greater than zero")
    return round(number, 2)


_PRODUCT_SELECT = """
    SELECT p.product_id, p.product_name, p.category_id, p.supplier_id, p.unit_price,
           p.quantity_in_stock, p.reorder_level,
           COALESCE(c.category_name, '') AS category_name,
           COALESCE(s.supplier_name, '') AS supplier_name
    FROM product p
    LEFT JOIN category c ON c.category_id = p.category_id
    LEFT JOIN supplier s ON s.supplier_id = p.supplier_id
"""


def _to_product(row) -> Product:
    return Product(row["product_id"], row["product_name"], row["category_id"], row["supplier_id"],
                   row["unit_price"], row["quantity_in_stock"], row["reorder_level"],
                   row["category_name"], row["supplier_name"])


class InventoryManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # ---------------- products ----------------
    def add_product(self, name, category_id, supplier_id, unit_price, quantity, reorder_level) -> int:
        name = _text(name, "Product name")
        price = _price(unit_price)
        quantity = _whole_number(quantity, "Quantity")
        reorder_level = _whole_number(reorder_level, "Reorder level")
        try:
            cur = self.db.execute(
                "INSERT INTO product (product_name, category_id, supplier_id, unit_price, "
                "quantity_in_stock, reorder_level) VALUES (?,?,?,?,?,?)",
                (name, category_id, supplier_id, price, quantity, reorder_level))
        except sqlite3.IntegrityError:
            raise ValidationError("Product already exists")
        return cur.lastrowid

    def update_product(self, product_id, name, category_id, supplier_id, unit_price, quantity, reorder_level) -> None:
        if self.get_product(product_id) is None:
            raise ValidationError("Product not found")
        name = _text(name, "Product name")
        price = _price(unit_price)
        quantity = _whole_number(quantity, "Quantity")
        reorder_level = _whole_number(reorder_level, "Reorder level")
        try:
            self.db.execute(
                "UPDATE product SET product_name=?, category_id=?, supplier_id=?, unit_price=?, "
                "quantity_in_stock=?, reorder_level=? WHERE product_id=?",
                (name, category_id, supplier_id, price, quantity, reorder_level, product_id))
        except sqlite3.IntegrityError:
            raise ValidationError("Another product already uses that name")

    def delete_product(self, product_id) -> None:
        try:
            self.db.execute("DELETE FROM product WHERE product_id = ?", (product_id,))
        except sqlite3.IntegrityError:
            raise ValidationError("This product has sales or stock history and cannot be deleted")

    def get_product(self, product_id) -> Optional[Product]:
        row = self.db.fetch_one(_PRODUCT_SELECT + " WHERE p.product_id = ?", (product_id,))
        return _to_product(row) if row else None

    def list_products(self) -> List[Product]:
        return [_to_product(r) for r in self.db.fetch_all(_PRODUCT_SELECT + " ORDER BY p.product_name")]

    def search_products(self, term: str) -> List[Product]:
        """Search by name, category or product ID (code). An empty term returns everything."""
        term = (term or "").strip()
        if not term:
            return self.list_products()
        like = f"%{term}%"
        rows = self.db.fetch_all(
            _PRODUCT_SELECT + " WHERE p.product_name LIKE ? OR c.category_name LIKE ? "
            "OR CAST(p.product_id AS TEXT) = ? ORDER BY p.product_name", (like, like, term))
        return [_to_product(r) for r in rows]

    def get_low_stock(self) -> List[Product]:
        rows = self.db.fetch_all(
            _PRODUCT_SELECT + " WHERE p.quantity_in_stock <= p.reorder_level "
            "ORDER BY p.quantity_in_stock ASC, p.product_name")
        return [_to_product(r) for r in rows]

    # ---------------- categories ----------------
    def list_categories(self) -> list:
        return self.db.fetch_all("SELECT * FROM category ORDER BY category_name")

    def add_category(self, name) -> int:
        name = _text(name, "Category name")
        try:
            return self.db.execute("INSERT INTO category (category_name) VALUES (?)", (name,)).lastrowid
        except sqlite3.IntegrityError:
            raise ValidationError("Category already exists")

    # ---------------- suppliers ----------------
    def add_supplier(self, name, contact_person="", phone="", email="", address="") -> int:
        name = _text(name, "Supplier name")
        email = (email or "").strip()
        if email and ("@" not in email or "." not in email.split("@")[-1]):
            raise ValidationError("Please enter a valid email address")
        try:
            cur = self.db.execute(
                "INSERT INTO supplier (supplier_name, contact_person, phone, email, address) VALUES (?,?,?,?,?)",
                (name, (contact_person or "").strip(), (phone or "").strip(), email, (address or "").strip()))
        except sqlite3.IntegrityError:
            raise ValidationError("Supplier already exists")
        return cur.lastrowid

    def update_supplier(self, supplier_id, name, contact_person="", phone="", email="", address="") -> None:
        name = _text(name, "Supplier name")
        email = (email or "").strip()
        if email and ("@" not in email or "." not in email.split("@")[-1]):
            raise ValidationError("Please enter a valid email address")
        try:
            self.db.execute(
                "UPDATE supplier SET supplier_name=?, contact_person=?, phone=?, email=?, address=? "
                "WHERE supplier_id=?",
                (name, (contact_person or "").strip(), (phone or "").strip(), email,
                 (address or "").strip(), supplier_id))
        except sqlite3.IntegrityError:
            raise ValidationError("Another supplier already uses that name")

    def delete_supplier(self, supplier_id) -> None:
        in_use = self.db.fetch_one("SELECT COUNT(*) AS n FROM product WHERE supplier_id = ?", (supplier_id,))["n"]
        if in_use:
            raise ValidationError(f"{in_use} product(s) use this supplier. Change those products first")
        try:
            self.db.execute("DELETE FROM supplier WHERE supplier_id = ?", (supplier_id,))
        except sqlite3.IntegrityError:
            raise ValidationError("This supplier has stock receipt history and cannot be deleted")

    def get_supplier(self, supplier_id) -> Optional[Supplier]:
        r = self.db.fetch_one("SELECT * FROM supplier WHERE supplier_id = ?", (supplier_id,))
        return Supplier(r["supplier_id"], r["supplier_name"], r["contact_person"], r["phone"],
                        r["email"], r["address"]) if r else None

    def list_suppliers(self) -> List[Supplier]:
        return [Supplier(r["supplier_id"], r["supplier_name"], r["contact_person"], r["phone"],
                         r["email"], r["address"])
                for r in self.db.fetch_all("SELECT * FROM supplier ORDER BY supplier_name")]

    # ---------------- receiving stock ----------------
    def receive_stock(self, product_id, supplier_id, quantity, user_id) -> None:
        """Record a delivery and increase the stock level (as one transaction)."""
        quantity = _whole_number(quantity, "Quantity received", minimum=1)
        product = self.get_product(product_id)
        if product is None:
            raise ValidationError("Please select a product")
        supplier_id = supplier_id or product.supplier_id
        if supplier_id is None or self.get_supplier(supplier_id) is None:
            raise ValidationError("Please select a supplier")
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO stock_receipt (product_id, supplier_id, user_id, quantity_received, date_received) "
                "VALUES (?,?,?,?,?)",
                (product_id, supplier_id, user_id, quantity, datetime.now().strftime(DATE_FORMAT)), commit=False)
            self.db.execute("UPDATE product SET quantity_in_stock = quantity_in_stock + ? WHERE product_id = ?",
                            (quantity, product_id), commit=False)
