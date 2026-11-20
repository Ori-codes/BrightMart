"""Sales: building a sale, completing it and updating stock automatically."""
import sqlite3
from datetime import datetime

from database import DATE_FORMAT, DatabaseManager
from models import Sale, ValidationError

STORE_NAME = "BrightMart Traders"


class SalesManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def start_sale(self, user_id: int) -> Sale:
        return Sale(user_id=user_id)

    def complete_sale(self, sale: Sale) -> int:
        """Save the sale and reduce stock. Everything happens in ONE transaction, so if
        anything fails (including a power cut) no partial sale is left in the database."""
        if not sale.items:
            raise ValidationError("Add at least one product to the sale")
        when = datetime.now().strftime(DATE_FORMAT)
        try:
            with self.db.transaction():
                for item in sale.items:  # re-check stock against the database, not the screen
                    current = self.db.fetch_one(
                        "SELECT quantity_in_stock FROM product WHERE product_id = ?",
                        (item.product.product_id,))
                    if current is None:
                        raise ValidationError(f"{item.product.name} no longer exists")
                    if item.quantity > current["quantity_in_stock"]:
                        raise ValidationError(
                            f"Insufficient stock for {item.product.name}. "
                            f"Available: {current['quantity_in_stock']}")
                cur = self.db.execute(
                    "INSERT INTO sale (user_id, sale_datetime, total_amount) VALUES (?,?,?)",
                    (sale.user_id, when, sale.calculate_total()), commit=False)
                sale_id = cur.lastrowid
                for item in sale.items:
                    self.db.execute(
                        "INSERT INTO sale_item (sale_id, product_id, quantity, unit_price, line_total) "
                        "VALUES (?,?,?,?,?)",
                        (sale_id, item.product.product_id, item.quantity, item.unit_price, item.line_total()),
                        commit=False)
                    self.db.execute(
                        "UPDATE product SET quantity_in_stock = quantity_in_stock - ? WHERE product_id = ?",
                        (item.quantity, item.product.product_id), commit=False)
        except sqlite3.Error:
            raise ValidationError("The sale could not be saved. No changes were made. Please try again")
        sale.sale_id, sale.sale_datetime = sale_id, when
        return sale_id

    def get_sales_by_date(self, start: str, end: str) -> list:
        return self.db.fetch_all(
            "SELECT * FROM sale WHERE date(sale_datetime) BETWEEN ? AND ? ORDER BY sale_datetime", (start, end))

    @staticmethod
    def build_receipt(sale: Sale) -> str:
        lines = [STORE_NAME, f"Receipt #{sale.sale_id}   {sale.sale_datetime}", "-" * 42]
        for item in sale.items:
            lines.append(f"{item.product.name[:24]:<24} {item.quantity:>3} x {item.unit_price:>6.2f} = {item.line_total():>7.2f}")
        lines += ["-" * 42, f"TOTAL: R {sale.calculate_total():.2f}", "Thank you for shopping with us!"]
        return "\n".join(lines)
