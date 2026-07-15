#!/usr/bin/env bash
# Rust coverage gate for the whole workspace (≥ 93% lines)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
export PATH="${HOME}/.local/protoc/bin:${PATH:-}"

# Libraries only (binaries are thin wrappers around libs).
cargo llvm-cov --workspace --lib --fail-under-lines 93 --summary-only
