import argparse
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup, NavigableString
from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DETAIL_EXTRACTION_VERSION = 2
UC_HOST = "techtransfer.universityofcalifornia.edu"
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
CHUNK_TOKENS = 200
OVERLAP_TOKENS = 24


def extract_sections(html):
    soup = BeautifulSoup(html, "html.parser")
    detail = soup.select_one(".ncd-data.fields")
    if detail is None:
        return None

    # Remove hidden blocks before reading the listing text.
    for element in reversed(detail.select("script, style, template, [hidden]")):
        element.decompose()

    sections = []
    heading = "Description"
    parts = []

    for node in detail.descendants:
        if getattr(node, "name", None) in HEADINGS:
            if parts:
                sections.append((heading, " ".join(parts)))
                parts = []

            label = " ".join(node.get_text(" ", strip=True).split())
            heading = label.rstrip(":").strip() or "Description"

        elif type(node) is NavigableString:
            if any(parent.name in HEADINGS for parent in node.parents):
                continue

            text = str(node).strip()
            if text:
                parts.append(text)

    if parts:
        sections.append((heading, " ".join(parts)))

    return sections


def make_chunks(model, title, sections):
    tokenizer = model.tokenizer
    chunks = []

    for heading, text in sections:
        prefix = f"{title}\n{heading}\n"
        prefix_length = len(tokenizer.encode(prefix, verbose=False))
        window = min(CHUNK_TOKENS, model.max_seq_length - prefix_length - 4)

        if window <= OVERLAP_TOKENS:
            prefix = ""
            special_tokens = tokenizer.num_special_tokens_to_add()
            window = min(CHUNK_TOKENS, model.max_seq_length - special_tokens - 4)

        # Tokenize the full section to find character offsets for each chunk.
        offsets = tokenizer(
            text,
            add_special_tokens=False,
            truncation=False,
            return_offsets_mapping=True,
            verbose=False,
        )["offset_mapping"]

        step = window - OVERLAP_TOKENS
        for start in range(0, len(offsets), step):
            end = min(start + window, len(offsets))
            excerpt = text[offsets[start][0] : offsets[end - 1][1]]
            chunks.append((heading.casefold(), excerpt, prefix + excerpt))
            if end == len(offsets):
                break

    return chunks


def main():
    parser = argparse.ArgumentParser(description="Embed UC technology detail pages.")
    parser.add_argument("--limit", type=int, default=10, help="Use 0 for all pending listings.")
    parser.add_argument("--write", action="store_true", help="Save text and embeddings to Atlas.")
    args = parser.parse_args()

    if args.limit < 0:
        parser.error("--limit must be zero or positive.")

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    uri = os.getenv("MONGODB_URI")
    if not uri:
        raise SystemExit("Set MONGODB_URI in the repo root's .env file.")

    with MongoClient(uri, serverSelectionTimeoutMS=10000) as client, requests.Session() as session:
        listings = client["iwa"]["ip_records"]
        chunk_collection = client["iwa"]["ip_record_chunks"]

        # Revisit listings embedded by the earlier extractor.
        pending = {
            "_id": {"$regex": "^uc-techtransfer:"},
            "detail_extraction_version": {"$ne": DETAIL_EXTRACTION_VERSION},
        }

        records = list(
            listings.find(pending, {"title": 1, "source_url": 1})
            .sort("_id", 1)
            .limit(args.limit)
        )

        if not records:
            print("No pending listings.")
            return

        model = SentenceTransformer(MODEL_NAME)
        embedded = 0
        empty_pages = 0
        fetch_failures = 0
        parse_failures = 0

        for number, record in enumerate(records, start=1):
            record_id = record["_id"]
            title = record["title"]
            url = record["source_url"]
            parsed_url = urlsplit(url)
            progress = f"[{number}/{len(records)}]"

            if parsed_url.scheme != "https" or parsed_url.hostname != UC_HOST:
                fetch_failures += 1
                print(f"{progress} Unexpected source URL for {record_id}")
                continue

            time.sleep(1)
            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
            except requests.HTTPError as error:
                status = error.response.status_code
                if status in {403, 429}:
                    raise SystemExit(f"UC returned HTTP {status}. Stopping.")
                fetch_failures += 1
                print(f"{progress} HTTP {status}: {url}")
                continue
            except requests.RequestException as error:
                fetch_failures += 1
                print(f"{progress} Fetch failed for {url}: {error}")
                continue

            final_url = urlsplit(response.url)
            if (
                final_url.scheme != "https"
                or final_url.hostname != UC_HOST
                or final_url.path.casefold() != parsed_url.path.casefold()
            ):
                parse_failures += 1
                print(f"{progress} Unexpected final URL for {record_id}: {response.url}")
                continue

            sections = extract_sections(response.text)
            if sections is None:
                parse_failures += 1
                print(f"{progress} Detail container missing: {url}")
                continue

            patent_sections = [
                body for heading, body in sections
                if heading.casefold() == "patent status"
            ]
            description_sections = [
                (heading, body) for heading, body in sections
                if heading.casefold() != "patent status"
            ]

            detail_text = "\n\n".join(
                f"{heading}\n{body}" for heading, body in description_sections
            )
            chunks = make_chunks(model, title, description_sections)

            fields = {
                "detail_text": detail_text,
                "patent_status": "\n".join(patent_sections) or None,
                "detail_chunk_count": len(chunks),
                "detail_extraction_version": DETAIL_EXTRACTION_VERSION,
            }

            if not chunks:
                if detail_text:
                    parse_failures += 1
                    print(f"{progress} Detail text produced no tokens: {url}")
                    continue

                empty_pages += 1
                print(f"{progress} No description text: {url}")
                if args.write:
                    chunk_collection.delete_many({"record_id": record_id})
                    listings.update_one(
                        {"_id": record_id},
                        {
                            "$set": {**fields, "detail_status": "no_detail_text"},
                            "$unset": {"detail_embedding_model": ""},
                        },
                    )
                continue

            vectors = model.encode(
                [embedding_text for _, _, embedding_text in chunks],
                normalize_embeddings=True,
            )

            if args.write:
                operations = []
                for position, ((section, excerpt, _), vector) in enumerate(
                    zip(chunks, vectors, strict=True)
                ):
                    chunk_id = f"{record_id}:{position}"
                    document = {
                        "_id": chunk_id,
                        "record_id": record_id,
                        "position": position,
                        "title": title,
                        "source_url": url,
                        "section": section,
                        "text": excerpt,
                        "embedding": vector.tolist(),
                        "embedding_model": MODEL_NAME,
                    }
                    operations.append(ReplaceOne({"_id": chunk_id}, document, upsert=True))

                chunk_collection.bulk_write(operations)
                chunk_collection.delete_many({
                    "record_id": record_id,
                    "position": {"$gte": len(chunks)},
                })

                # Mark the listing complete after its chunks are saved.
                listings.update_one(
                    {"_id": record_id},
                    {"$set": {
                        **fields,
                        "detail_status": "embedded",
                        "detail_embedding_model": MODEL_NAME,
                    }},
                )

            embedded += 1
            action = "Saved" if args.write else "Generated"
            print(f"{progress} {action} {len(chunks)} chunks: {title}")

        print(f"\nListings with chunks: {embedded}/{len(records)}")
        print(f"Pages with no description text: {empty_pages}")
        print(f"Fetch failures: {fetch_failures}")
        print(f"Parsing failures: {parse_failures}")


if __name__ == "__main__":
    main()