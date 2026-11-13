# IWA IP embeddings

We took the UC Tech Transfer listings and made them searchable by meaning. We saved one MiniLM embedding for each listing's title and summary (when it had one), then split the main text on each listing page into smaller passages and embedded those too. That way, a search can pull up the specific part of the listing that matches what you’re looking for.

## MongoDB Contents

| Collection | What it stores |
| --- | --- |
| `iwa.ip_records` | One document per IP listing with the title, summary, source URL, listing-level embedding, and detail chunk count. |
| `iwa.ip_record_chunks` | One document per passage with its text, section, position, and its own embedding. The `record_id` links it back to the listing. |

A **chunk** is a short passage from a listing page. A listing can have several sections, and a long section can be split into multiple passages with a little overlap so the text keeps its context. Each passage gets its own embedding.

For example, **Nematode-Resistant Grape Rootstocks** is one document in `ip_records`. Its full description was split into two documents in `ip_record_chunks`. Both have `record_id: "uc-techtransfer:10240"`, with positions `0` and `1` showing the order they appear on the page.

Both types of embeddings have 384 dimensions. Listings marked `no_detail_text` still have a listing-level embedding and have zero detail chunks.

## How to check and run it

**Check in Atlas.** In **Data Explorer → iwa-dev → iwa**, paste each filter into its collection and click **Find**.

| Collection | Filter | What to check |
| --- | --- | --- |
| `ip_records` | `{ "_id": "uc-techtransfer:10240" }` | One listing with `embedding: Array (384)`. |
| `ip_record_chunks` | `{ "record_id": "uc-techtransfer:10240" }` | The passages for that listing, each with `text` and `embedding: Array (384)`. |

**Try a search.** From the repo root, install dependencies and set `MONGODB_URI` in your local `.env`. With the team's Atlas indexes already set up, run:

```bash
python -m pip install -r requirements.txt
python mongoDB-setup/search_ip_records.py "ways to store energy from solar panels"
python mongoDB-setup/search_ip_chunks.py "grape rootstocks that resist nematodes"
```

The chunk search should show **Nematode-Resistant Grape Rootstocks** once, with its best matching passage.

**Generate embeddings for pending listings.** Once the listings are in `ip_records`, run:

```bash
python mongoDB-setup/embed_ip_records.py --limit 0 --write
python mongoDB-setup/embed_ip_details.py --limit 0 --write
```

Use `--limit 10` without `--write` to preview a small batch.