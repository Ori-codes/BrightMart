"""Report generation: sales, inventory and low-stock reports, with CSV export."""
import csv
from datetime import datetime, timedelta

from database import DatabaseManager
from inventory import InventoryManager
from models import ValidationError


def _parse_date(value: str) -> str:
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValidationError("Dates must be in the format YYYY-MM-DD (e.g. 2026-11-16)")


class ReportGenerator:
    """Each report is a dict: {'title', 'headers', 'rows', 'summary'}."""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.inventory = InventoryManager(db)

    def sales_report(self, start: str, end: str) -> dict:
        start, end = _parse_date(start), _parse_date(end)
        if start > end:
            raise ValidationError("The start date must not be after the end date")
        totals = self.db.fetch_all(
            "SELECT date(sale_datetime) AS day, COUNT(*) AS n, SUM(total_amount) AS revenue FROM sale "
            "WHERE date(sale_datetime) BETWEEN ? AND ? GROUP BY day ORDER BY day", (start, end))
        items = {r["day"]: r["units"] for r in self.db.fetch_all(
            "SELECT date(s.sale_datetime) AS day, SUM(si.quantity) AS units FROM sale s "
            "JOIN sale_item si ON si.sale_id = s.sale_id "
            "WHERE date(s.sale_datetime) BETWEEN ? AND ? GROUP BY day", (start, end))}
        rows = [(r["day"], r["n"], items.get(r["day"], 0), round(r["revenue"], 2)) for r in totals]
        revenue = round(sum(r[3] for r in rows), 2)
        summary = {"Period": f"{start} to {end}", "Number of sales": sum(r[1] for r in rows),
                   "Items sold": sum(r[2] for r in rows), "Total revenue (R)": f"{revenue:.2f}"}
        top = self.top_products(start, end, 1)
        if top:
            summary["Top-selling product"] = f"{top[0][0]} ({top[0][1]} units)"
        return {"title": f"Sales report: {start} to {end}",
                "headers": ["Date", "Number of sales", "Items sold", "Revenue (R)"],
                "rows": rows, "summary": summary}

    def daily_sales_report(self, day: str) -> dict:
        """Per-product breakdown of one day's sales."""
        day = _parse_date(day)
        rows = self.db.fetch_all(
            "SELECT p.product_name AS name, SUM(si.quantity) AS units, SUM(si.line_total) AS revenue "
            "FROM sale s JOIN sale_item si ON si.sale_id = s.sale_id "
            "JOIN product p ON p.product_id = si.product_id "
            "WHERE date(s.sale_datetime) = ? GROUP BY p.product_id ORDER BY revenue DESC", (day,))
        data = [(r["name"], r["units"], round(r["revenue"], 2)) for r in rows]
        count = self.db.fetch_one("SELECT COUNT(*) AS n FROM sale WHERE date(sale_datetime) = ?", (day,))["n"]
        return {"title": f"Daily sales report: {day}",
                "headers": ["Product", "Units sold", "Revenue (R)"], "rows": data,
                "summary": {"Date": day, "Number of sales": count,
                            "Total revenue (R)": f"{sum(r[2] for r in data):.2f}"}}

    def weekly_sales_report(self, week_start: str) -> dict:
        """Seven days starting from the given date, one row per day."""
        start = datetime.strptime(_parse_date(week_start), "%Y-%m-%d")
        report = self.sales_report(start.strftime("%Y-%m-%d"), (start + timedelta(days=6)).strftime("%Y-%m-%d"))
        report["title"] = "Weekly " + report["title"][0].lower() + report["title"][1:]
        return report

    def top_products(self, start: str, end: str, limit: int = 5) -> list:
        rows = self.db.fetch_all(
            "SELECT p.product_name AS name, SUM(si.quantity) AS units FROM sale s "
            "JOIN sale_item si ON si.sale_id = s.sale_id JOIN product p ON p.product_id = si.product_id "
            "WHERE date(s.sale_datetime) BETWEEN ? AND ? GROUP BY p.product_id "
            "ORDER BY units DESC, name LIMIT ?", (start, end, limit))
        return [(r["name"], r["units"]) for r in rows]

    def inventory_report(self) -> dict:
        products = self.inventory.list_products()
        rows = [(p.product_id, p.name, p.category_name, p.supplier_name, p.quantity_in_stock,
                 f"{p.unit_price:.2f}", f"{p.quantity_in_stock * p.unit_price:.2f}",
                 "LOW STOCK" if p.is_low_stock() else "OK") for p in products]
        value = sum(p.quantity_in_stock * p.unit_price for p in products)
        return {"title": "Inventory report",
                "headers": ["ID", "Product", "Category", "Supplier", "In stock", "Price (R)", "Stock value (R)", "Status"],
                "rows": rows,
                "summary": {"Products": len(products), "Total stock value (R)": f"{value:.2f}",
                            "Low-stock products": sum(1 for p in products if p.is_low_stock())}}

    def low_stock_report(self) -> dict:
        low = self.inventory.get_low_stock()
        rows = []
        for p in low:
            supplier = self.inventory.get_supplier(p.supplier_id) if p.supplier_id else None
            rows.append((p.product_id, p.name, p.quantity_in_stock, p.reorder_level,
                         p.supplier_name, supplier.phone if supplier else ""))
        return {"title": "Low-stock report",
                "headers": ["ID", "Product", "In stock", "Reorder level", "Supplier", "Supplier phone"],
                "rows": rows, "summary": {"Products needing re-order": len(rows)}}

    @staticmethod
    def export_to_csv(report: dict, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([report["title"]])
            writer.writerow(report["headers"])
            writer.writerows(report["rows"])
            writer.writerow([])
            for key, value in report["summary"].items():
                writer.writerow([key, value])
