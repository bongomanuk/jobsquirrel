#!/usr/bin/env bash
# Convenience entry point — install the pipeline's software into a local venv.
#   ./install.sh            # install
#   ./install.sh --check    # report what is present/missing
exec bash "$(dirname "$0")/tools/install.sh" "$@"
