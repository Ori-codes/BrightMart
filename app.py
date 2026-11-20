"""BrightMart Traders - web interface (Flask + HTML/CSS).

This file replaces gui.py. All business logic still lives in the manager classes
(auth.py, inventory.py, sales.py, reports.py); the routes below only collect form
input, call those classes and hand the results to the HTML templates.

Run:  python app.py            (then open http://127.0.0.1:5000)
      python app.py --demo     (with sample data)
      python app.py --network  (let a tablet on the shop Wi-Fi connect - trusted networks only)
"""
import csv
import hmac
import io
import os
import secrets
import sys
from functools import wraps

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for

from auth import ROLES, AuthManager
from database import DatabaseManager, seed_defaults, seed_demo_data
from inventory import InventoryManager
from models import User, ValidationError
from reports import ReportGenerator
from sales import STORE_NAME, SalesManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "brightmart.db")

REPORT_TYPES = [
    ("daily", "Daily sales (products sold on one date)"),
    ("weekly", "Weekly sales (7 days from start date)"),
    ("range", "Sales by date range"),
    ("inventory", "Inventory report"),
    ("low", "Low-stock report"),
]


def _secret_key() -> str:
    """Create a random secret key once and keep it in secret.key (used to sign login sessions)."""
    path = os.path.join(BASE_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def create_app(db_path: str = DEFAULT_DB, demo: bool = False, secret_key: str = None) -> Flask:
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secret_key or _secret_key(), DB_PATH=db_path,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

    setup = DatabaseManager(db_path)
    seed_defaults(setup)
    if demo:
        seed_demo_data(setup)
    setup.close()

    # ------------------------------------------------------------ per-request setup
    @app.before_request
    def load_request():
        g.db = DatabaseManager(app.config["DB_PATH"])
        g.auth = AuthManager(g.db)
        g.inventory = InventoryManager(g.db)
        g.sales = SalesManager(g.db)
        g.reports = ReportGenerator(g.db)
        user_id = session.get("user_id")
        if user_id:
            row = g.db.fetch_one("SELECT user_id, username, full_name, role FROM user WHERE user_id = ?", (user_id,))
            if row:
                g.auth.current_user = User(row["user_id"], row["username"], row["full_name"], row["role"])
            else:
                session.clear()
        if request.method == "POST":  # CSRF protection: every form carries a secret token
            sent = request.form.get("_csrf", "")
            if not sent or not hmac.compare_digest(sent, session.get("_csrf", "")):
                abort(400)

    @app.teardown_request
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def template_globals():
        user = g.auth.current_user if "auth" in g else None
        low = g.inventory.get_low_stock() if user and g.auth.has_permission("view_alerts") else None
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return {"store_name": STORE_NAME, "user": user, "can": g.auth.has_permission if "auth" in g else (lambda a: False),
                "low_stock": low, "csrf_token": session["_csrf"], "endpoint": request.endpoint or ""}

    @app.template_filter("money")
    def money(value):
        return f"R\u00a0{float(value):,.2f}".replace(",", "\u00a0")

    def requires(permission=None):
        def decorator(view):
            @wraps(view)
            def wrapper(*args, **kwargs):
                if g.auth.current_user is None:
                    return redirect(url_for("login"))
                if permission and not g.auth.has_permission(permission):
                    abort(403)
                return view(*args, **kwargs)
            return wrapper
        return decorator

    # ------------------------------------------------------------ login / logout
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            try:
                user = g.auth.login(request.form.get("username"), request.form.get("password"))
            except ValidationError as err:
                flash(str(err), "error")
                return render_template("login.html"), 401
            session.clear()
            session["user_id"] = user.user_id
            return redirect(url_for("home"))
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @requires()
    def home():
        for permission, endpoint in (("record_sale", "sales"), ("view_stock", "inventory"), ("view_reports", "reports")):
            if g.auth.has_permission(permission):
                return redirect(url_for(endpoint))
        abort(403)

    # ------------------------------------------------------------ sales
    def current_sale():
        """Rebuild the sale in progress from the session (product id -> quantity)."""
        sale = g.sales.start_sale(g.auth.current_user.user_id)
        for pid, qty in list(session.get("cart", {}).items()):
            product = g.inventory.get_product(int(pid))
            try:
                if product is None:
                    raise ValidationError("A product in the sale no longer exists")
                sale.add_item(product, qty)
            except ValidationError as err:
                flash(f"{err}. It was removed from the sale.", "warning")
        save_cart(sale)
        return sale

    def save_cart(sale):
        session["cart"] = {str(i.product.product_id): i.quantity for i in sale.items}

    @app.route("/sales")
    @requires("record_sale")
    def sales():
        query = request.args.get("q", "")
        return render_template("sales.html", sale=current_sale(), products=g.inventory.search_products(query),
                               q=query, receipt=session.pop("receipt", None))

    @app.route("/sales/add", methods=["POST"])
    @requires("record_sale")
    def sales_add():
        sale = current_sale()
        try:
            product = g.inventory.get_product(int(request.form.get("product_id", 0)))
            if product is None:
                raise ValidationError("Please select a product")
            try:
                quantity = int(request.form.get("quantity", "1"))
            except ValueError:
                raise ValidationError("Quantity must be a whole number")
            sale.add_item(product, quantity)
            save_cart(sale)
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("sales", q=request.form.get("q", "")))

    @app.route("/sales/remove", methods=["POST"])
    @requires("record_sale")
    def sales_remove():
        sale = current_sale()
        sale.remove_item(int(request.form.get("product_id", 0)))
        save_cart(sale)
        return redirect(url_for("sales", q=request.form.get("q", "")))

    @app.route("/sales/cancel", methods=["POST"])
    @requires("record_sale")
    def sales_cancel():
        session.pop("cart", None)
        flash("The sale was cancelled.", "warning")
        return redirect(url_for("sales"))

    @app.route("/sales/complete", methods=["POST"])
    @requires("record_sale")
    def sales_complete():
        sale = current_sale()
        try:
            g.sales.complete_sale(sale)
        except ValidationError as err:
            flash(str(err), "error")
            return redirect(url_for("sales"))
        session["receipt"] = g.sales.build_receipt(sale)
        session.pop("cart", None)
        flash("Sale completed. Stock has been updated.", "success")
        return redirect(url_for("sales"))

    # ------------------------------------------------------------ inventory
    @app.route("/inventory")
    @requires("view_stock")
    def inventory():
        query = request.args.get("q", "")
        return render_template("inventory.html", products=g.inventory.search_products(query), q=query)

    def product_choices():
        return g.inventory.list_categories(), g.inventory.list_suppliers()

    def product_form(product=None):
        form = request.form if request.method == "POST" else {}
        categories, suppliers = product_choices()
        return render_template("product_form.html", product=product, form=form, categories=categories, suppliers=suppliers)

    def _int_or_none(value):
        return int(value) if value and value.isdigit() else None

    @app.route("/inventory/new", methods=["GET", "POST"])
    @requires("manage_products")
    def product_new():
        if request.method == "POST":
            f = request.form
            try:
                g.inventory.add_product(f.get("name"), _int_or_none(f.get("category_id")), _int_or_none(f.get("supplier_id")),
                                        f.get("price"), f.get("quantity"), f.get("reorder_level"))
            except ValidationError as err:
                flash(str(err), "error")
                return product_form()
            flash("Product added.", "success")
            return redirect(url_for("inventory"))
        return product_form()

    @app.route("/inventory/<int:pid>/edit", methods=["GET", "POST"])
    @requires("manage_products")
    def product_edit(pid):
        product = g.inventory.get_product(pid) or abort(404)
        if request.method == "POST":
            f = request.form
            try:
                g.inventory.update_product(pid, f.get("name"), _int_or_none(f.get("category_id")), _int_or_none(f.get("supplier_id")),
                                           f.get("price"), f.get("quantity"), f.get("reorder_level"))
            except ValidationError as err:
                flash(str(err), "error")
                return product_form(product)
            flash("Product updated.", "success")
            return redirect(url_for("inventory"))
        return product_form(product)

    @app.route("/inventory/<int:pid>/delete", methods=["POST"])
    @requires("manage_products")
    def product_delete(pid):
        try:
            g.inventory.delete_product(pid)
            flash("Product deleted.", "success")
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("inventory"))

    @app.route("/inventory/<int:pid>/receive", methods=["GET", "POST"])
    @requires("receive_stock")
    def product_receive(pid):
        product = g.inventory.get_product(pid) or abort(404)
        if request.method == "POST":
            try:
                g.inventory.receive_stock(pid, _int_or_none(request.form.get("supplier_id")),
                                          request.form.get("quantity"), g.auth.current_user.user_id)
                flash(f"Stock received for {product.name}.", "success")
                return redirect(url_for("inventory"))
            except ValidationError as err:
                flash(str(err), "error")
        return render_template("receive.html", product=product, suppliers=g.inventory.list_suppliers(), form=request.form)

    # ------------------------------------------------------------ suppliers
    @app.route("/suppliers")
    @requires("manage_suppliers")
    def suppliers():
        return render_template("suppliers.html", suppliers=g.inventory.list_suppliers())

    def supplier_fields():
        f = request.form
        return f.get("name"), f.get("contact_person"), f.get("phone"), f.get("email"), f.get("address")

    @app.route("/suppliers/new", methods=["GET", "POST"])
    @requires("manage_suppliers")
    def supplier_new():
        if request.method == "POST":
            try:
                g.inventory.add_supplier(*supplier_fields())
                flash("Supplier added.", "success")
                return redirect(url_for("suppliers"))
            except ValidationError as err:
                flash(str(err), "error")
        return render_template("supplier_form.html", supplier=None, form=request.form)

    @app.route("/suppliers/<int:sid>/edit", methods=["GET", "POST"])
    @requires("manage_suppliers")
    def supplier_edit(sid):
        supplier = g.inventory.get_supplier(sid) or abort(404)
        if request.method == "POST":
            try:
                g.inventory.update_supplier(sid, *supplier_fields())
                flash("Supplier updated.", "success")
                return redirect(url_for("suppliers"))
            except ValidationError as err:
                flash(str(err), "error")
        return render_template("supplier_form.html", supplier=supplier, form=request.form)

    @app.route("/suppliers/<int:sid>/delete", methods=["POST"])
    @requires("manage_suppliers")
    def supplier_delete(sid):
        try:
            g.inventory.delete_supplier(sid)
            flash("Supplier deleted.", "success")
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("suppliers"))

    # ------------------------------------------------------------ reports
    def build_report(kind, start, end):
        r = g.reports
        if kind == "daily":
            return r.daily_sales_report(start)
        if kind == "weekly":
            return r.weekly_sales_report(start)
        if kind == "range":
            return r.sales_report(start, end)
        if kind == "inventory":
            return r.inventory_report()
        if kind == "low":
            return r.low_stock_report()
        raise ValidationError("Please choose a report type")

    @app.route("/reports")
    @requires("view_reports")
    def reports():
        from datetime import datetime, timedelta
        today = datetime.now()
        kind = request.args.get("type", "")
        start = request.args.get("start") or (today - timedelta(days=6)).strftime("%Y-%m-%d")
        end = request.args.get("end") or today.strftime("%Y-%m-%d")
        report = None
        if kind:
            try:
                report = build_report(kind, start, end)
            except ValidationError as err:
                flash(str(err), "error")
        return render_template("reports.html", types=REPORT_TYPES, kind=kind, start=start, end=end, report=report)

    @app.route("/reports/export")
    @requires("view_reports")
    def reports_export():
        try:
            report = build_report(request.args.get("type", ""), request.args.get("start", ""), request.args.get("end", ""))
        except ValidationError as err:
            flash(str(err), "error")
            return redirect(url_for("reports"))
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([report["title"]])
        writer.writerow(report["headers"])
        writer.writerows(report["rows"])
        writer.writerow([])
        for key, value in report["summary"].items():
            writer.writerow([key, value])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=brightmart_report.csv"})

    # ------------------------------------------------------------ users
    @app.route("/users")
    @requires("manage_users")
    def users():
        return render_template("users.html", users=g.auth.list_users(), roles=ROLES, form={})

    @app.route("/users/add", methods=["POST"])
    @requires("manage_users")
    def user_add():
        f = request.form
        try:
            g.auth.create_user(f.get("username"), f.get("password"), f.get("full_name"), f.get("role"))
            flash("User added.", "success")
            return redirect(url_for("users"))
        except ValidationError as err:
            flash(str(err), "error")
        return render_template("users.html", users=g.auth.list_users(), roles=ROLES, form=f)

    @app.route("/users/<int:uid>/delete", methods=["POST"])
    @requires("manage_users")
    def user_delete(uid):
        try:
            g.auth.delete_user(uid)
            flash("User deleted.", "success")
        except ValidationError as err:
            flash(str(err), "error")
        return redirect(url_for("users"))

    # ------------------------------------------------------------ errors
    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="You do not have permission to open this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="That page could not be found."), 404

    @app.errorhandler(400)
    def bad_request(_e):
        return render_template("error.html", code=400, message="The form expired or was invalid. Please go back and try again."), 400

    return app


if __name__ == "__main__":
    application = create_app(demo="--demo" in sys.argv)
    host = "0.0.0.0" if "--network" in sys.argv else "127.0.0.1"
    print(f"BrightMart is running. Open http://127.0.0.1:5000 in your browser (Ctrl+C to stop).")
    application.run(host=host, port=5000, debug=False)
