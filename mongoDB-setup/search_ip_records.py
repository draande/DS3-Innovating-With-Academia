import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise SystemExit("Set MONGODB_URI in the repo root's .env file.")

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    vector = model.encode(args.query, normalize_embeddings=True).tolist()

    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        collection = client["iwa"]["ip_records"]
        results = list(collection.aggregate([
            {"$vectorSearch": {
                "index": "ip_embedding_index",
                "path": "embedding",
                "queryVector": vector,
                "exact": True,
                "limit": 5,
            }},
            {"$project": {
                "_id": 0,
                "title": 1,
                "source_url": 1,
                "score": {"$meta": "vectorSearchScore"},
            }},
        ]))

    if not results:
        print("No results returned.")
    for rank, result in enumerate(results, start=1):
        print(f"{rank}. {result['title']} ({result['score']:.3f})")
        print(f"   {result['source_url']}")


if __name__ == "__main__":
    main()