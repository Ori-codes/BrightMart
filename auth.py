"""Authentication and role-based access control."""
import sqlite3

from database import DatabaseManager
from models import User, ValidationError
from security import hash_password, verify_password

ROLES = ("Store Manager", "Sales Staff", "Business Owner")

_ALL_ACTIONS = {
    "search_products", "view_stock", "record_sale", "manage_products", "manage_suppliers",
    "receive_stock", "view_alerts", "view_reports", "manage_users",
}

# What each role may do (matches the use case diagram in the report).
PERMISSIONS = {
    "Store Manager": set(_ALL_ACTIONS),
    "Sales Staff": {"search_products", "view_stock", "record_sale"},
    "Business Owner": {"search_products", "view_stock", "view_alerts", "view_reports"},
}


class AuthManager:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.current_user = None

    def login(self, username: str, password: str) -> User:
        username = (username or "").strip()
        if not username or not password:
            raise ValidationError("Please enter username and password")
        row = self.db.fetch_one("SELECT * FROM user WHERE username = ?", (username,))
        if row is None or not verify_password(password, row["password_hash"]):
            raise ValidationError("Invalid username or password")
        self.current_user = User(row["user_id"], row["username"], row["full_name"], row["role"])
        return self.current_user

    def logout(self) -> None:
        self.current_user = None

    def has_permission(self, action: str) -> bool:
        return self.current_user is not None and action in PERMISSIONS[self.current_user.role]

    def require(self, action: str) -> None:
        if not self.has_permission(action):
            raise PermissionError("You do not have permission to do this")

    # ---- user management (Store Manager only) ----
    def create_user(self, username: str, password: str, full_name: str, role: str) -> int:
        self.require("manage_users")
        username, full_name = (username or "").strip(), (full_name or "").strip()
        if not username or not full_name:
            raise ValidationError("Username and full name are required")
        if len(password or "") < 6:
            raise ValidationError("Password must be at least 6 characters")
        if role not in ROLES:
            raise ValidationError("Please choose a valid role")
        try:
            cur = self.db.execute(
                "INSERT INTO user (username, password_hash, full_name, role) VALUES (?,?,?,?)",
                (username, hash_password(password), full_name, role))
        except sqlite3.IntegrityError:
            raise ValidationError("That username already exists")
        return cur.lastrowid

    def list_users(self) -> list:
        self.require("manage_users")
        return self.db.fetch_all("SELECT user_id, username, full_name, role FROM user ORDER BY username")

    def delete_user(self, user_id: int) -> None:
        self.require("manage_users")
        if user_id == self.current_user.user_id:
            raise ValidationError("You cannot delete the account you are logged in with")
        try:
            self.db.execute("DELETE FROM user WHERE user_id = ?", (user_id,))
        except sqlite3.IntegrityError:
            raise ValidationError("This user has recorded sales or stock receipts and cannot be deleted")
