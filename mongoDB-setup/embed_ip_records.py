import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
BATCH_SIZE = 32


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10, help="Use 0 for all pending records.")
    parser.add_argument("--write", action="store_true", help="Save embeddings to Atlas.")
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit must be zero or positive.")

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise SystemExit("Set MONGODB_URI in the repo root's .env file.")

    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        collection = client["iwa"]["ip_records"]
        query = {
            "_id": {"$regex": "^uc-techtransfer:"},
            "$or": [
                {"embedding": {"$exists": False}},
                {"embedding_model": {"$ne": MODEL_NAME}},
            ],
        }
        records = list(
            collection.find(query, {"title": 1, "summary": 1})
            .sort("_id", 1)
            .limit(args.limit)
        )

        if not records:
            print("No pending records.")
            return

        model = SentenceTransformer(MODEL_NAME)
        for start in range(0, len(records), BATCH_SIZE):
            batch = records[start : start + BATCH_SIZE]
            texts = [
                "\n".join(filter(None, [record["title"], record.get("summary")]))
                for record in batch
            ]
            vectors = model.encode(texts, normalize_embeddings=True)

            if args.write:
                collection.bulk_write([
                    UpdateOne(
                        {"_id": record["_id"]},
                        {"$set": {
                            "embedding": vector.tolist(),
                            "embedding_model": MODEL_NAME,
                        }},
                    )
                    for record, vector in zip(batch, vectors)
                ])

            action = "Saved" if args.write else "Generated"
            print(f"{action} {start + len(batch)}/{len(records)} embeddings ({vectors.shape[1]} dimensions)")


if __name__ == "__main__":
    main()