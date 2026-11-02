# Storage

The pipeline keeps a lot of machine-local data, and most of it compresses hard:
run logs, the Gmail body cache, and the GraphRAG indexing cache. None of it is
committed; it lives only on your machine.

    python3 tools/storage.py                    # report: what is using space
    python3 tools/storage.py --logs             # gzip logs idle for a day
    python3 tools/storage.py --pack-log X.log   # gzip one finished transcript
    python3 tools/storage.py --state            # pack cold per-role artifacts
    python3 tools/storage.py --hydrate-all      # restore everything, in place
    python3 tools/storage.py --hydrate acme-eng # restore one role's artifacts
    python3 tools/storage.py --gmail-cache      # gzip state/gmail_cache.json
    python3 tools/storage.py --graphrag-cache   # dry run: what archiving saves
    python3 tools/storage.py --all --apply      # everything, including the archive

## What each action does

**`--logs`** gzips `state/logs/*.log|*.out|*.err` that have not been touched for a
day, and `kb/graphrag/logs/` after 2 days (an indexing run finishes in hours, so a
two-day-old index log is idle). A log being written right now is never moved, and
the append-only logs are excluded by name (`dashboard-chat.log`,
`dashboard-action.log`, `approval.log`, `run_queue.out`, `linkedin_run.out`,
`human_assist.out`, `reconcile.log`, `camoufox_server*.log`): gzipping one of
those would corrupt it on the next append. Override the window with `--days`.

**`--pack-log PATH`** gzips one specific log immediately. The queue runners call
it as soon as a role finishes, so a run's transcript is history the moment the
role is done, rather than a day later.

The two logs that really are appended to are capped instead: when
`dashboard-chat.log` or `dashboard-action.log` passes 2 MB, the dashboard rolls it
to `dashboard-chat-<date>.log.gz` and restarts the live file empty, so yesterday's
transcript is kept (and still listed as a task log) without an unbounded plain
file.

The dashboard reads both forms: `foo.log.gz` still appears as task `foo`.

**`--state`** packs the per-role artifacts — `state/job-descriptions/`,
`state/ats/`, `state/kb-context/`, `state/cv-content/`, `state/letters-content/`,
`state/gates/` and the register digest — once they are older than the window
(7 days by default, `--state-days` overrides it). They are text, so they shrink
2-4x; a fresh artifact from today's run is left alone.

Packing is invisible because `tools/stateio.py` resolves `x` or `x.gz` for every
reader: `jd_guard`, `ats_keywords`, `kb_graphrag`, `check_alignment`,
`cv_target`, `check_documents`, `gate_receipt` (a packed receipt still satisfies
`record_submission`), and the dashboard, which reads the packed twin rather than
restoring it — browsing the grid never undoes the saving. Anything that needs a
real file calls `stateio.ensure()`, which restores it in place and keeps the
artifact's original age.

A queue run restores everything at the start (`--hydrate-all`) so the runner and
the agent always see plain paths, and packs the cold leftovers when it finishes.
To restore by hand: `--hydrate-all`, or `--hydrate <key>` for one role.

Two things are deliberately never packed: files that are appended to or written
by shell redirection (`queue*.tsv`, `*.done`, `*.csv`, `state/drafts/`), and
symlinks (some older role keys are links to the canonical slug).

**Files git tracks are left plain by default.** Packing one shows up as a deletion
plus an untracked `.gz`, and every pack/hydrate cycle would churn the repo; git
already zlib-compresses blobs and delta-packs them, so `git gc` handles that side.
`--include-tracked` overrides it if you have untracked the per-role artifacts on
purpose (for example after `git rm --cached` them).

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
unpacked.

`.git/` is git's own compression problem, and a checkout that has been committing
documents for weeks slowly fills with loose objects. One command reclaims it:

    git gc --prune=now        # 118 MB -> 36 MB in a typical busy checkout

`tools/storage.py` does not run it for you: it rewrites the object database, so
it is a git decision, not a file-compression one.

## Backups and the data lifecycle

`tools/backup.py` (Settings → **Backup & data**) is the other half of storage:
`--state`/`--logs` shrink what is there, a backup lets you move or rebuild it.
A backup zip holds `config/`, `answers/`, `kb/sources/`, `state/` (minus logs and
the mail cache) and optionally `documents/`; the GraphRAG index is excluded
because it is rebuildable from the sources.

Anything destructive — restore or clear — writes an automatic safety copy to
`backups/` first (`pre-restore-*.zip`, `pre-clear-*.zip`), and only the newest
five of those are kept. Your own `jobsquirrel-*.zip` backups are never pruned.
`backups/` is git-ignored: it contains personal data.

## Checking

`python3 tools/doctor.py` includes a `storage` line with the current sizes of
logs, the Gmail cache and the GraphRAG cache, plus what compression could reclaim
right now. `tests/test_storage.py` covers the log and cache round-trips and the
dashboard's compressed-log reader.
