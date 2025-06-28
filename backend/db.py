# backend/db.py
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
db = client["inventory_db"]
inventory_collection = db["inventory"]
