import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    parser = argparse.ArgumentParser(description="Search UC IP listing passages.")
    parser.add_argument("query", help="Search text in quotes.")
    args = parser.parse_args()

    query = args.query.strip()
    if not query:
        parser.error("Enter a search query.")

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise SystemExit("Set MONGODB_URI in the repo root's .env file.")

    model = SentenceTransformer(MODEL_NAME)
    vector = model.encode(query, normalize_embeddings=True).tolist()

    pipeline = [
        {
            "$vectorSearch": {
                "index": "ip_chunk_embedding_index",
                "path": "embedding",
                "queryVector": vector,
                "exact": True,
                "limit": 25,
            }
        },
        {
            "$project": {
                "_id": 0,
                "title": 1,
                "record_id": 1,
                "section": 1,
                "text": 1,
                "source_url": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client:
        collection = client["iwa"]["ip_record_chunks"]
        results = list(collection.aggregate(pipeline))
    
    if not results:
        print("No results returned. Check that ip_chunk_embedding_index is queryable.")
        return

    seen_ids = set()
    unique_results = []

    # Results are ranked by score, so the first chunk per listing is its best match.
    for result in results:
        record_id = result["record_id"]
        if record_id in seen_ids:
            continue

        seen_ids.add(record_id)
        unique_results.append(result)
        if len(unique_results) == 5:
            break

    for rank, result in enumerate(unique_results, start=1):
        print(f"\n{rank}. {result['title']} ({result['score']:.3f})")
        print(f"   {result['record_id']} | {result['section']}")
        print(f"   {result['source_url']}")
        print(f"   {result['text']}")


if __name__ == "__main__":
    main()