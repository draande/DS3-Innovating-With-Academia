import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

with MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=5000) as client:
    records = client["iwa"]["ip_records"]
    records.update_one(
        {"_id": "atlas-test"},
        {"$set": {"title": "Atlas connection test"}},
        upsert=True,
    )
    print(records.find_one({"_id": "atlas-test"}))