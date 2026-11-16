## What this changes

## Why

## Checklist

- [ ] No person- or country-specific defaults added to `tools/` (all config lives in `config/`)
- [ ] Gates (`check_documents.py`, `check_alignment.py`, `facts.py`) not weakened
- [ ] `python3 -m py_compile tools/*.py` passes (use `.venv/bin/python`)
- [ ] `bash -n tools/*.sh install.sh` passes
- [ ] No personal details leak in: `grep -rniE "<your-name>|<your-city>|<your-employer>" . | grep -v ".git/"` returns nothing
- [ ] Docs updated (`AGENTS.md` / `BOOTSTRAP.md` / `docs/`) when behaviour or modes change
