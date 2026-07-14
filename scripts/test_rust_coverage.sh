#!/usr/bin/env bash
# Rust coverage gate for fgg-core (≥ 93% lines)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PATH="${HOME}/.local/protoc/bin:${PATH:-}"

cargo llvm-cov -p fgg-core --lib --fail-under-lines 93 --summary-only
