"""Tests for the Flask web interface (run: python -m unittest discover -s tests -v)."""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database import DatabaseManager


class WebTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.app = create_app(os.path.join(self.dir, "t.db"), demo=True, secret_key="test-key")
        self.client = self.app.test_client()

    def token(self, path="/login"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf" value="([0-9a-f]+)"', html).group(1)

    def login(self, user, password):
        return self.client.post("/login", data={"username": user, "password": password, "_csrf": self.token()})

    def post(self, path, page="/inventory", **data):
        data["_csrf"] = self.token(page)
        return self.client.post(path, data=data)

    def stock(self, name):
        db = DatabaseManager(self.app.config["DB_PATH"])
        row = db.fetch_one("SELECT product_id, quantity_in_stock FROM product WHERE product_name = ?", (name,))
        db.close()
        return row["product_id"], row["quantity_in_stock"]


class TestAccess(WebTest):
    def test_login_required(self):
        for path in ("/", "/sales", "/inventory", "/reports", "/suppliers", "/users"):
            self.assertEqual(self.client.get(path).status_code, 302, path)

    def test_bad_login(self):
        r = self.login("manager", "wrong")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Invalid username or password", r.get_data(as_text=True))

    def test_csrf_blocks_forms_without_token(self):
        self.assertEqual(self.client.post("/login", data={"username": "manager", "password": "manager123"}).status_code, 400)

    def test_manager_sees_everything(self):
        self.assertEqual(self.login("manager", "manager123").status_code, 302)
        for path in ("/sales", "/inventory", "/suppliers", "/reports", "/users", "/inventory/new"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_sales_staff_is_restricted(self):
        self.login("sales", "sales123")
        self.assertEqual(self.client.get("/sales").status_code, 200)
        self.assertEqual(self.client.get("/inventory").status_code, 200)
        for path in ("/suppliers", "/reports", "/users", "/inventory/new"):
            self.assertEqual(self.client.get(path).status_code, 403, path)

    def test_owner_is_read_only(self):
        self.login("owner", "owner123")
        self.assertEqual(self.client.get("/reports").status_code, 200)
        self.assertEqual(self.client.get("/sales").status_code, 403)
        self.assertEqual(self.client.get("/inventory/new").status_code, 403)

    def test_logout(self):
        self.login("manager", "manager123")
        self.post("/logout", page="/sales")
        self.assertEqual(self.client.get("/sales").status_code, 302)


class TestFeatures(WebTest):
    def setUp(self):
        super().setUp()
        self.login("manager", "manager123")

    def test_theme_and_logo_assets_are_served(self):
        html = self.client.get("/sales").get_data(as_text=True)
        self.assertIn("theme-toggle", html)
        self.assertIn('name="viewport"', html)
        for path in ("/static/css/style.css", "/static/js/theme.js", "/static/img/logo.svg"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_low_stock_banner(self):
        self.assertIn("Low stock:", self.client.get("/inventory").get_data(as_text=True))

    def test_add_edit_delete_product(self):
        self.post("/inventory/new", page="/inventory/new", name="Test Item", price="12.5", quantity="9", reorder_level="3",
                  category_id="", supplier_id="")
        pid, qty = self.stock("Test Item")
        self.assertEqual(qty, 9)
        self.post(f"/inventory/{pid}/edit", page=f"/inventory/{pid}/edit", name="Test Item", price="15", quantity="4",
                  reorder_level="3", category_id="", supplier_id="")
        self.assertEqual(self.stock("Test Item")[1], 4)
        self.post(f"/inventory/{pid}/delete")
        self.assertNotIn("Test Item", self.client.get("/inventory").get_data(as_text=True))

    def test_validation_message_shown(self):
        r = self.post("/inventory/new", page="/inventory/new", name="", price="-1", quantity="1", reorder_level="1")
        self.assertIn("required", r.get_data(as_text=True))

    def test_sale_flow_reduces_stock(self):
        pid, before = self.stock("White Bread 700g")
        self.post("/sales/add", page="/sales", product_id=pid, quantity="3")
        page = self.client.get("/sales").get_data(as_text=True)
        self.assertIn("R\u00a055.50", page)  # 3 x 18.50
        self.post("/sales/complete", page="/sales")
        self.assertEqual(self.stock("White Bread 700g")[1], before - 3)
        self.assertIn("Receipt", self.client.get("/sales").get_data(as_text=True))

    def test_cannot_oversell(self):
        pid, before = self.stock("White Bread 700g")
        r = self.client.post("/sales/add", data={"product_id": pid, "quantity": before + 1, "_csrf": self.token("/sales")},
                             follow_redirects=True)
        self.assertIn("Insufficient stock", r.get_data(as_text=True))
        self.assertEqual(self.stock("White Bread 700g")[1], before)

    def test_remove_and_cancel(self):
        pid, _ = self.stock("Maize Meal 5kg")
        self.post("/sales/add", page="/sales", product_id=pid, quantity="1")
        self.post("/sales/remove", page="/sales", product_id=pid)
        self.assertIn("No items yet", self.client.get("/sales").get_data(as_text=True))

    def test_receive_stock(self):
        pid, before = self.stock("A4 Notebook 72pg")
        self.post(f"/inventory/{pid}/receive", page=f"/inventory/{pid}/receive", supplier_id="", quantity="20")
        self.assertEqual(self.stock("A4 Notebook 72pg")[1], before + 20)

    def test_suppliers_and_users(self):
        self.post("/suppliers/new", page="/suppliers/new", name="NewCo", contact_person="X", phone="1", email="a@b.co", address="Z")
        self.assertIn("NewCo", self.client.get("/suppliers").get_data(as_text=True))
        self.post("/users/add", page="/users", username="thandi", full_name="Thandi", password="secret1", role="Sales Staff")
        self.assertIn("thandi", self.client.get("/users").get_data(as_text=True))

    def test_reports_and_csv(self):
        for kind in ("daily", "weekly", "range", "inventory", "low"):
            r = self.client.get(f"/reports?type={kind}")
            self.assertEqual(r.status_code, 200, kind)
        csv_response = self.client.get("/reports/export?type=inventory")
        self.assertEqual(csv_response.mimetype, "text/csv")
        self.assertIn("Inventory report", csv_response.get_data(as_text=True))
        bad = self.client.get("/reports?type=range&start=2026-12-01&end=2026-11-01")
        self.assertIn("must not be after", bad.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
