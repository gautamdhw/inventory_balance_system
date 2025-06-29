from flask import Flask, request, session, redirect, render_template, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
from db import inventory_collection, store_admins_collection, sales_collection, prediction_collection
import os
import pandas as pd
from werkzeug.utils import secure_filename
from sklearn.linear_model import LinearRegression
from datetime import datetime, timedelta
import numpy as np

app = Flask(__name__, template_folder="../frontend/templates", static_folder="../frontend/static")
app.secret_key = "supersecretkey"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def home():
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        store_id = request.form["store_id"]
        password = request.form["password"]
        if store_admins_collection.find_one({"store_id": store_id}):
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
    if user and check_password_hash(user["password"], password):
        session["store_id"] = store_id
        return redirect("/dashboard")
    else:
        return "Invalid store ID or password"

@app.route("/dashboard")
def dashboard():
    if "store_id" not in session:
        return redirect("/")
    store_id = session["store_id"]

    # Inventory
    records = list(inventory_collection.find({"store_id": store_id}))
    table_rows = "".join([f"<tr><td>{i.get('item_id')}</td><td>{i.get('product')}</td><td>{i.get('stock')}</td></tr>" for i in records])

    # Sales
    sales = list(sales_collection.find({"store_id": store_id}))
    sales_rows = "".join([f"<tr><td>{s.get('date')}</td><td>{s.get('item_id')}</td><td>{s.get('product')}</td><td>{s.get('quantity')}</td></tr>" for s in sales])

    return render_template("index.html", store_id=store_id, table_rows=table_rows, sales_rows=sales_rows)

@app.route("/api/inventory/upload", methods=["POST"])
def upload_inventory():
    if "store_id" not in session:
        return redirect("/")
    file = request.files["file"]
    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    file.save(filepath)
    df = pd.read_csv(filepath)
    df["store_id"] = session["store_id"]
    inventory_collection.delete_many({"store_id": session["store_id"]})
    inventory_collection.insert_many(df.to_dict(orient="records"))
    return redirect("/dashboard")

@app.route("/api/sales/upload", methods=["POST"])
def upload_sales():
    if "store_id" not in session:
        return redirect("/")
    file = request.files["file"]
    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
    file.save(filepath)
    df = pd.read_csv(filepath)
    df["store_id"] = session["store_id"]
    sales_collection.delete_many({"store_id": session["store_id"]})
    sales_collection.insert_many(df.to_dict(orient="records"))
    return redirect("/dashboard")

@app.route("/predict", methods=["POST", "GET"])
def predict():
    if "store_id" not in session:
        return redirect("/")

    store_id = session["store_id"]

    # Load sales data
    sales_data = list(sales_collection.find({"store_id": store_id}))
    df = pd.DataFrame(sales_data)

    if df.empty or "date" not in df.columns:
        return "No sales data found."

    # Preprocess
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df = df.dropna(subset=["date", "quantity", "item_id"])
    df["day"] = (df["date"] - df["date"].min()).dt.days

    # Remove previous predictions
    prediction_collection.delete_many({"store_id": store_id})
    
    # Fetch current inventory for this store
    inventory_data = {item["item_id"]: item.get("stock", 0) for item in inventory_collection.find({"store_id": store_id})}

    prediction_rows = ""

    for item_id in df["item_id"].unique():
        item_df = df[df["item_id"] == item_id]

        if len(item_df) < 2:
            continue

        X = item_df["day"].values.reshape(-1, 1)
        y = item_df["quantity"].values
        model = LinearRegression()
        model.fit(X, y)

        last_day = item_df["day"].max()
        start_date = item_df["date"].max()
        end_date = start_date + timedelta(days=7)

        total_predicted = 0

        for i in range(1, 8):
            future_day = int(last_day + i)
            pred_qty = model.predict(np.array([[future_day]]))[0]
            total_predicted += max(0, round(pred_qty))

        # 🧮 Compare with inventory
        current_stock = inventory_data.get(item_id, 0)
        difference = current_stock - total_predicted
        status = "Surplus" if difference >= 0 else "Shortage"

        # Store in MongoDB
        prediction_collection.insert_one({
            "store_id": store_id,
            "item_id": item_id,
            "start_date": (start_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "predicted_quantity": total_predicted,
            "current_stock": current_stock,
            "difference": difference,
            "status": status
        })

        # Show in HTML
        prediction_rows += f"""
            <tr>
              <td>{item_id}</td>
              <td>{(start_date + timedelta(days=1)).strftime('%Y-%m-%d')}</td>
              <td>{end_date.strftime('%Y-%m-%d')}</td>
              <td>{total_predicted}</td>
              <td>{current_stock}</td>
              <td>{abs(difference)}</td>
              <td>{status}</td>
            </tr>
        """

    return render_template("predict.html", store_id=store_id, prediction_rows=prediction_rows)






@app.route("/predict-page", methods=["GET"])
def predict_page():
    if "store_id" not in session:
        return redirect("/")

    store_id = session["store_id"]
    predictions = prediction_collection.find({"store_id": store_id})

    prediction_rows = ""
    for p in predictions:
        prediction_rows += f"""
            <tr>
              <td>{p.get('item_id')}</td>
              <td>{p.get('start_date')}</td>
              <td>{p.get('end_date')}</td>
              <td>{p.get('predicted_quantity')}</td>
              <td>{p.get('current_stock')}</td>
              <td>{abs(p.get('difference', 0))}</td>
              <td>{p.get('status')}</td>
            </tr>
        """

    return render_template("predict.html", store_id=store_id, prediction_rows=prediction_rows)



@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
