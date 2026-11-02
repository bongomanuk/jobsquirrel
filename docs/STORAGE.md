# Storage

The pipeline keeps a lot of machine-local data, and most of it compresses hard:
run logs, the Gmail body cache, and the GraphRAG indexing cache. None of it is
committed; it lives only on your machine.

    python3 tools/storage.py                    # report: what is using space
    python3 tools/storage.py --logs             # gzip logs older than 7 days
    python3 tools/storage.py --gmail-cache      # gzip state/gmail_cache.json
    python3 tools/storage.py --graphrag-cache   # dry run: what archiving saves
    python3 tools/storage.py --all --apply      # everything, including the archive

## What each action does

**`--logs`** gzips `state/logs/*.log` that have not been touched for 7 days, and
`kb/graphrag/logs/*.log` after 2 days (an indexing run finishes in hours, so a
two-day-old index log is idle). A log being written right now is never moved.
It runs automatically at the start of every queue run, which is what keeps
`state/logs/` bounded. The dashboard reads both forms: `foo.log.gz` still appears
as task `foo`.

**`--gmail-cache`** gzips `state/gmail_cache.json` (roughly 9x smaller). The cache
holds decoded message bodies keyed by id; it is derived data and can be deleted at
any time. `gmail_reconcile.py` and `gmail_review_model.py` read either form, and
`save_cache` keeps the compressed form when that is what it finds, so the next
reconcile does not re-inflate it.

**`--graphrag-cache`** tars `kb/graphrag/cache/` into
`kb/archives/graphrag-cache-<date>.tar.zst` and removes the loose files (roughly
6x smaller). This cache only speeds up (re)indexing — queries read
`kb/graphrag/output/`, so retrieval keeps working without it, and the archive is
restorable if you would rather keep the incremental-index history:

    python3 tools/storage.py --graphrag-cache --apply
    tar -C kb/graphrag -xf kb/archives/graphrag-cache-<date>.tar.zst \
        --use-compress-program=unzstd

It is a dry run unless you pass `--apply`, because it is the only action that
moves a large directory.

## What is not compressed

`documents/` holds `.docx` and `.pdf`, which are already compressed container
formats; re-packing them saves nothing and breaks the files. The GraphRAG
`output/` directory (LanceDB tables + parquet) is read at query time and must stay
unpacked. `.git/` is already packed; `git gc` is the right tool there, not gzip.

## Checking

`python3 tools/doctor.py` includes a `storage` line with the current sizes of
logs, the Gmail cache and the GraphRAG cache, plus what compression could reclaim
right now. `tests/test_storage.py` covers the log and cache round-trips and the
dashboard's compressed-log reader.
