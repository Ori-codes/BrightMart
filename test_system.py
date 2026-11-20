"""Automated tests for the BrightMart system (run: python -m unittest discover -s tests -v)."""
import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import AuthManager
from database import DATE_FORMAT, DatabaseManager, seed_defaults, seed_demo_data
from inventory import InventoryManager
from models import Product, ValidationError
from reports import ReportGenerator
from sales import SalesManager
from security import hash_password, verify_password


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager(":memory:")
        seed_defaults(self.db)
        self.auth = AuthManager(self.db)
        self.inv = InventoryManager(self.db)
        self.sales = SalesManager(self.db)
        self.reports = ReportGenerator(self.db)
        self.user = self.auth.login("manager", "manager123")
        self.sup = self.inv.add_supplier("CleanCo", "Anna", "012 555 0103", "info@cleanco.example")
        self.cat = self.inv.list_categories()[0]["category_id"]
        self.bread = self.inv.add_product("White Bread", self.cat, self.sup, "18.50", "10", "3")

    def tearDown(self):
        self.db.close()

    def stock(self, pid):
        return self.inv.get_product(pid).quantity_in_stock


class TestSecurityAndAuth(BaseTest):
    def test_password_is_hashed_and_verifies(self):
        stored = hash_password("secret1")
        self.assertNotIn("secret1", stored)
        self.assertTrue(verify_password("secret1", stored))
        self.assertFalse(verify_password("wrong", stored))
        self.assertNotEqual(hash_password("secret1"), hash_password("secret1"))  # random salt

    def test_login_valid_roles(self):
        self.assertEqual(self.auth.login("sales", "sales123").role, "Sales Staff")
        self.assertEqual(self.auth.login("owner", "owner123").role, "Business Owner")

    def test_login_invalid_and_empty(self):
        for u, p in [("manager", "bad"), ("nobody", "x"), ("", "x"), ("manager", "")]:
            with self.assertRaises(ValidationError):
                self.auth.login(u, p)

    def test_role_permissions(self):
        self.auth.login("sales", "sales123")
        self.assertTrue(self.auth.has_permission("record_sale"))
        self.assertFalse(self.auth.has_permission("manage_products"))
        self.assertFalse(self.auth.has_permission("view_reports"))
        self.auth.login("owner", "owner123")
        self.assertTrue(self.auth.has_permission("view_reports"))
        self.assertFalse(self.auth.has_permission("record_sale"))
        self.auth.logout()
        self.assertFalse(self.auth.has_permission("view_stock"))

    def test_user_management(self):
        uid = self.auth.create_user("thandi", "pass1234", "Thandi N", "Sales Staff")
        self.assertIn("thandi", [u["username"] for u in self.auth.list_users()])
        with self.assertRaises(ValidationError):
            self.auth.create_user("thandi", "pass1234", "Dup", "Sales Staff")
        with self.assertRaises(ValidationError):
            self.auth.create_user("x", "123", "Short pw", "Sales Staff")
        with self.assertRaises(ValidationError):
            self.auth.delete_user(self.user.user_id)  # cannot delete yourself
        self.auth.delete_user(uid)

    def test_non_manager_cannot_manage_users(self):
        self.auth.login("sales", "sales123")
        with self.assertRaises(PermissionError):
            self.auth.create_user("a", "pass1234", "A", "Sales Staff")


class TestProducts(BaseTest):
    def test_add_and_get(self):
        p = self.inv.get_product(self.bread)
        self.assertEqual((p.name, p.unit_price, p.quantity_in_stock), ("White Bread", 18.5, 10))
        self.assertEqual(p.supplier_name, "CleanCo")

    def test_validation(self):
        bad = [("", "5", "1", "1"), ("A", "0", "1", "1"), ("A", "-3", "1", "1"), ("A", "abc", "1", "1"),
               ("A", "5", "-1", "1"), ("A", "5", "x", "1"), ("A", "5", "1", "-2")]
        for name, price, qty, reorder in bad:
            with self.assertRaises(ValidationError, msg=(name, price, qty, reorder)):
                self.inv.add_product(name, self.cat, self.sup, price, qty, reorder)

    def test_duplicate_name_case_insensitive(self):
        with self.assertRaises(ValidationError):
            self.inv.add_product("white bread", self.cat, self.sup, "5", "1", "1")

    def test_update_and_delete(self):
        self.inv.update_product(self.bread, "White Bread 700g", self.cat, self.sup, "19.00", "12", "4")
        p = self.inv.get_product(self.bread)
        self.assertEqual((p.name, p.unit_price, p.quantity_in_stock, p.reorder_level), ("White Bread 700g", 19.0, 12, 4))
        self.inv.delete_product(self.bread)
        self.assertIsNone(self.inv.get_product(self.bread))

    def test_cannot_delete_product_with_sales(self):
        sale = self.sales.start_sale(self.user.user_id)
        sale.add_item(self.inv.get_product(self.bread), 1)
        self.sales.complete_sale(sale)
        with self.assertRaises(ValidationError):
            self.inv.delete_product(self.bread)

    def test_search(self):
        self.inv.add_product("Dish Soap", self.cat, self.sup, "30", "5", "2")
        self.assertEqual([p.name for p in self.inv.search_products("bread")], ["White Bread"])
        self.assertEqual(len(self.inv.search_products("")), 2)
        self.assertEqual(self.inv.search_products(str(self.bread))[0].product_id, self.bread)
        self.assertEqual(self.inv.search_products("zzz"), [])
        cat_name = self.inv.list_categories()[0]["category_name"]
        self.assertEqual(len(self.inv.search_products(cat_name)), 2)


class TestSuppliers(BaseTest):
    def test_crud_and_validation(self):
        sid = self.inv.add_supplier("PaperPlus", "Lerato", "012", "a@b.co", "Centurion")
        self.inv.update_supplier(sid, "PaperPlus SA", "Lerato D", "013", "a@b.co", "Midrand")
        self.assertEqual(self.inv.get_supplier(sid).supplier_name, "PaperPlus SA")
        with self.assertRaises(ValidationError):
            self.inv.add_supplier("")
        with self.assertRaises(ValidationError):
            self.inv.add_supplier("Bad Email", email="not-an-email")
        with self.assertRaises(ValidationError):
            self.inv.add_supplier("PaperPlus SA")
        self.inv.delete_supplier(sid)

    def test_cannot_delete_supplier_in_use(self):
        with self.assertRaises(ValidationError):
            self.inv.delete_supplier(self.sup)


class TestSales(BaseTest):
    def test_sale_reduces_stock_and_totals(self):
        soap = self.inv.add_product("Soap", self.cat, self.sup, "10.00", "20", "5")
        sale = self.sales.start_sale(self.user.user_id)
        sale.add_item(self.inv.get_product(self.bread), 2)
        sale.add_item(self.inv.get_product(soap), 3)
        self.assertEqual(sale.calculate_total(), 67.0)
        sale_id = self.sales.complete_sale(sale)
        self.assertEqual(self.stock(self.bread), 8)
        self.assertEqual(self.stock(soap), 17)
        row = self.db.fetch_one("SELECT * FROM sale WHERE sale_id = ?", (sale_id,))
        self.assertEqual(row["total_amount"], 67.0)
        self.assertEqual(len(self.db.fetch_all("SELECT * FROM sale_item WHERE sale_id = ?", (sale_id,))), 2)
        self.assertIn("TOTAL: R 67.00", self.sales.build_receipt(sale))

    def test_cannot_sell_more_than_stock(self):
        sale = self.sales.start_sale(self.user.user_id)
        with self.assertRaises(ValidationError):
            sale.add_item(self.inv.get_product(self.bread), 11)
        sale.add_item(self.inv.get_product(self.bread), 6)
        with self.assertRaises(ValidationError):  # 6 + 5 > 10
            sale.add_item(self.inv.get_product(self.bread), 5)

    def test_invalid_quantity(self):
        sale = self.sales.start_sale(self.user.user_id)
        for q in (0, -1):
            with self.assertRaises(ValidationError):
                sale.add_item(self.inv.get_product(self.bread), q)

    def test_same_product_twice_is_merged(self):
        sale = self.sales.start_sale(self.user.user_id)
        sale.add_item(self.inv.get_product(self.bread), 2)
        sale.add_item(self.inv.get_product(self.bread), 3)
        self.assertEqual(len(sale.items), 1)
        self.assertEqual(sale.items[0].quantity, 5)

    def test_empty_sale_rejected(self):
        with self.assertRaises(ValidationError):
            self.sales.complete_sale(self.sales.start_sale(self.user.user_id))

    def test_stock_rechecked_at_completion_and_rolled_back(self):
        soap = self.inv.add_product("Soap", self.cat, self.sup, "10.00", "5", "1")
        sale = self.sales.start_sale(self.user.user_id)
        sale.add_item(self.inv.get_product(self.bread), 2)
        sale.add_item(self.inv.get_product(soap), 5)
        # someone else sells soap before this sale is completed
        self.db.execute("UPDATE product SET quantity_in_stock = 1 WHERE product_id = ?", (soap,))
        with self.assertRaises(ValidationError):
            self.sales.complete_sale(sale)
        self.assertEqual(self.stock(self.bread), 10)  # nothing was changed
        self.assertEqual(self.db.fetch_one("SELECT COUNT(*) AS n FROM sale")["n"], 0)

    def test_remove_item(self):
        sale = self.sales.start_sale(self.user.user_id)
        sale.add_item(self.inv.get_product(self.bread), 2)
        sale.remove_item(self.bread)
        self.assertEqual(sale.calculate_total(), 0)

    def test_price_change_does_not_alter_past_sale(self):
        sale = self.sales.start_sale(self.user.user_id)
        sale.add_item(self.inv.get_product(self.bread), 1)
        sid = self.sales.complete_sale(sale)
        self.inv.update_product(self.bread, "White Bread", self.cat, self.sup, "99.00", "9", "3")
        self.assertEqual(self.db.fetch_one("SELECT unit_price FROM sale_item WHERE sale_id=?", (sid,))["unit_price"], 18.5)


class TestStockAndAlerts(BaseTest):
    def test_receive_stock(self):
        self.inv.receive_stock(self.bread, self.sup, "15", self.user.user_id)
        self.assertEqual(self.stock(self.bread), 25)
        self.assertEqual(self.db.fetch_one("SELECT COUNT(*) AS n FROM stock_receipt")["n"], 1)

    def test_receive_stock_validation(self):
        for q in ("0", "-5", "abc"):
            with self.assertRaises(ValidationError):
                self.inv.receive_stock(self.bread, self.sup, q, self.user.user_id)
        with self.assertRaises(ValidationError):
            self.inv.receive_stock(9999, self.sup, "5", self.user.user_id)

    def test_low_stock_alert_after_sale(self):
        self.assertEqual(self.inv.get_low_stock(), [])
        sale = self.sales.start_sale(self.user.user_id)
        sale.add_item(self.inv.get_product(self.bread), 7)  # 10 - 7 = 3 = reorder level
        self.sales.complete_sale(sale)
        self.assertEqual([p.name for p in self.inv.get_low_stock()], ["White Bread"])
        self.inv.receive_stock(self.bread, self.sup, "20", self.user.user_id)
        self.assertEqual(self.inv.get_low_stock(), [])

    def test_product_model_methods(self):
        p = Product(1, "X", None, None, 5.0, 4, 4)
        self.assertTrue(p.is_low_stock())
        p.increase_stock(3)
        self.assertFalse(p.is_low_stock())
        p.reduce_stock(7)
        self.assertEqual(p.quantity_in_stock, 0)
        with self.assertRaises(ValidationError):
            p.reduce_stock(1)


class TestReports(BaseTest):
    def _sale_on(self, days_ago, qty):
        sale = self.sales.start_sale(self.user.user_id)
        sale.add_item(self.inv.get_product(self.bread), qty)
        sid = self.sales.complete_sale(sale)
        when = (datetime.now() - timedelta(days=days_ago)).strftime(DATE_FORMAT)
        self.db.execute("UPDATE sale SET sale_datetime = ? WHERE sale_id = ?", (when, sid))

    def test_sales_report(self):
        self._sale_on(2, 1)
        self._sale_on(2, 2)
        self._sale_on(1, 1)
        start = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        rep = self.reports.sales_report(start, end)
        self.assertEqual(len(rep["rows"]), 2)
        self.assertEqual(rep["summary"]["Number of sales"], 3)
        self.assertEqual(rep["summary"]["Items sold"], 4)
        self.assertEqual(rep["summary"]["Total revenue (R)"], "74.00")

    def test_daily_and_weekly(self):
        self._sale_on(0, 2)
        today = datetime.now().strftime("%Y-%m-%d")
        daily = self.reports.daily_sales_report(today)
        self.assertEqual(daily["rows"][0][:2], ("White Bread", 2))
        weekly = self.reports.weekly_sales_report((datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d"))
        self.assertEqual(weekly["summary"]["Number of sales"], 1)

    def test_empty_period_and_bad_dates(self):
        self.assertEqual(self.reports.sales_report("2020-01-01", "2020-01-02")["rows"], [])
        with self.assertRaises(ValidationError):
            self.reports.sales_report("2026-12-01", "2026-11-01")
        with self.assertRaises(ValidationError):
            self.reports.sales_report("01/12/2026", "2026-12-02")

    def test_inventory_and_low_stock_reports(self):
        rep = self.reports.inventory_report()
        self.assertEqual(rep["summary"]["Total stock value (R)"], "185.00")
        self.db.execute("UPDATE product SET quantity_in_stock = 1 WHERE product_id = ?", (self.bread,))
        low = self.reports.low_stock_report()
        self.assertEqual(low["rows"][0][1], "White Bread")
        self.assertEqual(low["rows"][0][5], "012 555 0103")

    def test_csv_export(self):
        rep = self.reports.inventory_report()
        path = os.path.join(tempfile.mkdtemp(), "inv.csv")
        self.reports.export_to_csv(rep, path)
        with open(path, newline="", encoding="utf-8") as f:
            content = list(csv.reader(f))
        self.assertEqual(content[0][0], "Inventory report")
        self.assertEqual(content[1][1], "Product")
        self.assertEqual(content[2][1], "White Bread")


class TestDemoData(unittest.TestCase):
    def test_demo_seed_is_consistent(self):
        db = DatabaseManager(":memory:")
        seed_defaults(db)
        seed_demo_data(db)
        self.assertGreater(db.fetch_one("SELECT COUNT(*) AS n FROM sale")["n"], 50)
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS n FROM product WHERE quantity_in_stock < 0")["n"], 0)
        self.assertGreaterEqual(len(InventoryManager(db).get_low_stock()), 2)
        seed_demo_data(db)  # running twice must not duplicate
        self.assertEqual(db.fetch_one("SELECT COUNT(*) AS n FROM product")["n"], 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
