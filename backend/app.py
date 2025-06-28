from flask import Flask, request, session, redirect, render_template, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
from db import inventory_collection, store_admins_collection
import os
import pandas as pd
from werkzeug.utils import secure_filename



app = Flask(__name__, template_folder="../frontend/templates", static_folder="../frontend/static")
app.secret_key = "supersecretkey"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def home():
    return render_template("login.html")  # ✅ clean load from templates

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        store_id = request.form["store_id"]
        password = request.form["password"]

        existing = store_admins_collection.find_one({"store_id": store_id})
        if existing:
            return "Store ID already exists"

        hashed = generate_password_hash(password)
        store_admins_collection.insert_one({"store_id": store_id, "password": hashed})
        return redirect("/")

    return render_template("register.html")


@app.route("/login", methods=["POST"])
def login():
    store_id = request.form["store_id"]
    password = request.form["password"]

    user = store_admins_collection.find_one({"store_id": store_id})
    if not user or not check_password_hash(user["password"], password):
        return "Invalid credentials"

    session["store_id"] = store_id
    return redirect("/dashboard")


@app.route("/dashboard")
def dashboard():
    if "store_id" not in session:
        return redirect("/")

    store_id = session["store_id"]
    records = list(inventory_collection.find({"store_id": store_id}))
    table_rows = ""
    for item in records:
        table_rows += f"<tr><td>{item.get('item_id')}</td><td>{item.get('product')}</td><td>{item.get('stock')}</td></tr>"

    # ✅ send values via render_template
    return render_template("index.html", store_id=store_id, table_rows=table_rows)

@app.route("/api/inventory/upload", methods=["POST"])
def upload_inventory():
    if "store_id" not in session:
        return redirect("/")

    file = request.files["file"]
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    df = pd.read_csv(filepath)
    df["store_id"] = session["store_id"]

    # Clean previous data for that store
    inventory_collection.delete_many({"store_id": session["store_id"]})
    inventory_collection.insert_many(df.to_dict(orient="records"))

    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()  # or session.pop("store_id", None)
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)
