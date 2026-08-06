# Seed corpus

Drop the problem statement's documents here (`.txt .md .log .csv .json .pdf .png .jpg`),
then run from the repo root:

```bash
python db/vectordb/seed_vector_db.py --reset
```

Indexed through the same pipeline as an API upload: load → anonymise → chunk → embed →
upsert. Document ids come from the filename, so re-seeding replaces chunks instead of
duplicating them.

`chroma/` and `uploads/` beside this folder are generated and gitignored. The relational
store is separate, at `db/sqlite/data/app.db`.

[PLACEHOLDER: describe the actual corpus once the problem statement lands — what the
documents are, roughly how many, and which fields matter for retrieval.]
