"""Database layer: SQLite connection, schema creation and seed data.

The schema implements the ERD in the technical report (7 tables, 3NF).
"""
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

from security import hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('Store Manager', 'Sales Staff', 'Business Owner'))
);
CREATE TABLE IF NOT EXISTS category (
    category_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS supplier (
    supplier_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name  TEXT NOT NULL UNIQUE,
    contact_person TEXT DEFAULT '',
    phone          TEXT DEFAULT '',
    email          TEXT DEFAULT '',
    address        TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS product (
    product_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category_id       INTEGER REFERENCES category(category_id) ON DELETE SET NULL,
    supplier_id       INTEGER REFERENCES supplier(supplier_id) ON DELETE SET NULL,
    unit_price        REAL NOT NULL CHECK (unit_price > 0),
    quantity_in_stock INTEGER NOT NULL DEFAULT 0 CHECK (quantity_in_stock >= 0),
    reorder_level     INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0)
);
CREATE TABLE IF NOT EXISTS sale (
    sale_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES user(user_id),
    sale_datetime TEXT NOT NULL,
    total_amount  REAL NOT NULL CHECK (total_amount >= 0)
);
CREATE TABLE IF NOT EXISTS sale_item (
    sale_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id      INTEGER NOT NULL REFERENCES sale(sale_id) ON DELETE CASCADE,
    product_id   INTEGER NOT NULL REFERENCES product(product_id) ON DELETE RESTRICT,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   REAL NOT NULL,
    line_total   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_receipt (
    receipt_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id        INTEGER NOT NULL REFERENCES product(product_id),
    supplier_id       INTEGER NOT NULL REFERENCES supplier(supplier_id),
    user_id           INTEGER NOT NULL REFERENCES user(user_id),
    quantity_received INTEGER NOT NULL CHECK (quantity_received > 0),
    date_received     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sale_datetime ON sale(sale_datetime);
CREATE INDEX IF NOT EXISTS idx_sale_item_sale ON sale_item(sale_id);
CREATE INDEX IF NOT EXISTS idx_product_name ON product(product_name);
"""

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class DatabaseManager:
    """Thin wrapper around an SQLite connection (see class diagram)."""

    def __init__(self, db_path: str = "brightmart.db"):
        self.db_path = db_path
        self.conn = None
        self.connect()
        self.create_tables()

    def connect(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def create_tables(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def execute(self, sql: str, params=(), commit: bool = True) -> sqlite3.Cursor:
        cursor = self.conn.execute(sql, params)
        if commit:
            self.conn.commit()
        return cursor

    def fetch_all(self, sql: str, params=()) -> list:
        return self.conn.execute(sql, params).fetchall()

    def fetch_one(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchone()

    @contextmanager
    def transaction(self):
        """Run several statements as one unit: all succeed, or none are saved."""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None


def seed_defaults(db: DatabaseManager) -> None:
    """Create the default user accounts and categories on first run."""
    if db.fetch_one("SELECT 1 FROM user LIMIT 1") is None:
        users = [
            ("manager", "manager123", "Manager Account", "Store Manager"),
            ("sales", "sales123", "Sales Account", "Sales Staff"),
            ("owner", "owner123", "Owner Account", "Business Owner"),
        ]
        for username, password, full_name, role in users:
            db.execute("INSERT INTO user (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                       (username, hash_password(password), full_name, role))
    for name in ("Household Goods", "Stationery", "Convenience"):
        db.execute("INSERT OR IGNORE INTO category (category_name) VALUES (?)", (name,))


def seed_demo_data(db: DatabaseManager) -> None:
    """Add sample suppliers, products and 14 days of sales so reports have data."""
    if db.fetch_one("SELECT 1 FROM product LIMIT 1") is not None:
        return
    suppliers = [("Sunbake Foods", "Thabo Mokoena", "012 555 0101", "orders@sunbake.example", "Pretoria"),
                 ("PaperPlus", "Lerato Dlamini", "012 555 0102", "sales@paperplus.example", "Centurion"),
                 ("CleanCo", "Anna van Wyk", "012 555 0103", "info@cleanco.example", "Midrand")]
    for s in suppliers:
        db.execute("INSERT OR IGNORE INTO supplier (supplier_name, contact_person, phone, email, address) "
                   "VALUES (?,?,?,?,?)", s)
    cat = {r["category_name"]: r["category_id"] for r in db.fetch_all("SELECT * FROM category")}
    sup = {r["supplier_name"]: r["supplier_id"] for r in db.fetch_all("SELECT * FROM supplier")}
    products = [  # name, category, supplier, price, stock, reorder
        ("White Bread 700g", "Convenience", "Sunbake Foods", 18.50, 60, 20),
        ("Maize Meal 5kg", "Convenience", "Sunbake Foods", 59.90, 40, 12),
        ("Cooking Oil 750ml", "Convenience", "Sunbake Foods", 42.50, 35, 10),
        ("A4 Notebook 72pg", "Stationery", "PaperPlus", 12.00, 12, 15),
        ("Ballpoint Pens (box of 10)", "Stationery", "PaperPlus", 24.00, 9, 10),
        ("A4 Copy Paper (ream)", "Stationery", "PaperPlus", 79.00, 25, 8),
        ("Dishwashing Liquid 750ml", "Household Goods", "CleanCo", 32.90, 30, 10),
        ("Laundry Soap Bar", "Household Goods", "CleanCo", 9.90, 80, 25),
        ("Toilet Paper 9s", "Household Goods", "CleanCo", 64.00, 28, 10),
        ("Light Bulb LED 9W", "Household Goods", "CleanCo", 29.90, 18, 6),
    ]
    for name, c, s, price, stock, reorder in products:
        db.execute("INSERT INTO product (product_name, category_id, supplier_id, unit_price, "
                   "quantity_in_stock, reorder_level) VALUES (?,?,?,?,?,?)",
                   (name, cat[c], sup[s], price, stock, reorder))
    rng = random.Random(42)
    manager = db.fetch_one("SELECT user_id FROM user WHERE role = 'Store Manager'")["user_id"]
    prices = {r["product_id"]: r["unit_price"] for r in db.fetch_all("SELECT * FROM product")}
    product_ids = list(prices)
    now = datetime.now()
    # Sales history is sample data only; current stock levels stay as set above
    # (two products are deliberately below their reorder level to demonstrate alerts).
    with db.transaction():
        for days_ago in range(14, 0, -1):
            for _ in range(rng.randint(8, 16)):
                when = (now - timedelta(days=days_ago)).replace(
                    hour=rng.randint(8, 17), minute=rng.randint(0, 59), second=rng.randint(0, 59))
                lines = []
                for pid in rng.sample(product_ids, rng.randint(1, 3)):
                    qty = rng.randint(1, 3)
                    lines.append((pid, qty, prices[pid], round(qty * prices[pid], 2)))
                total = round(sum(l[3] for l in lines), 2)
                cur = db.execute("INSERT INTO sale (user_id, sale_datetime, total_amount) VALUES (?,?,?)",
                                 (manager, when.strftime(DATE_FORMAT), total), commit=False)
                for pid, qty, price, line in lines:
                    db.execute("INSERT INTO sale_item (sale_id, product_id, quantity, unit_price, line_total) "
                               "VALUES (?,?,?,?,?)", (cur.lastrowid, pid, qty, price, line), commit=False)
