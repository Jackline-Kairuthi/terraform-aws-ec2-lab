#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export TF_INPUT=0
export TF_IN_AUTOMATION=1
export AWS_PAGER=""
exec python3 "$project_dir/scripts/manage.py" "$@"
