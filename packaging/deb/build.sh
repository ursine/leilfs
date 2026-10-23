#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
output_dir=${LEILFS_DEB_OUTPUT_DIR:-"${source_dir}/_packages/debian"}
mkdir -p "${output_dir}"
output_dir=$(cd -- "${output_dir}" && pwd)
work_dir=$(mktemp -d "${output_dir}/source.XXXXXX")
cd "${source_dir}"
# Include current worktree edits, excluding ignored build/package artifacts.
# An isolated source copy keeps dh_clean away from other build directories and
# gives dpkg-buildpackage a writable parent for its output archives.
git ls-files --cached --others --exclude-standard -z |
    tar --null -T - -cf - | tar -xf - -C "${work_dir}"
printf 'Building in %s; packages will be written to %s\n' "${work_dir}" "${output_dir}"
cd "${work_dir}"
exec dpkg-buildpackage -b -us -uc "$@"
