#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SKILLS_SRC="${REPO_ROOT}/skills"
TEMPLATE_SRC="${REPO_ROOT}/templates/home-AGENTS.snippet.md"
CODEX_HOME_DIR="${CODEX_HOME:-${HOME}/.codex}"
SKILLS_DEST="${CODEX_HOME_DIR}/skills"
HOME_AGENTS="${HOME}/AGENTS.md"
# Keep the legacy marker names so an upgraded install replaces the older block cleanly.
MARKER_START="# >>> codex-skills gemini advisory >>>"
MARKER_END="# <<< codex-skills gemini advisory <<<"
INSTALL_HOME_AGENTS="false"

for arg in "$@"; do
  case "${arg}" in
    --install-home-agents)
      INSTALL_HOME_AGENTS="true"
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      echo "Usage: ./scripts/install.sh [--install-home-agents]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "${SKILLS_DEST}"

for skill_dir in "${SKILLS_SRC}"/*; do
  skill_name="$(basename "${skill_dir}")"
  dest="${SKILLS_DEST}/${skill_name}"
  rm -rf "${dest}"
  cp -R "${skill_dir}" "${dest}"
done

if [[ "${INSTALL_HOME_AGENTS}" == "true" ]]; then
  tmp_file="$(mktemp)"
  snippet_body="$(cat "${TEMPLATE_SRC}")"
  block="${MARKER_START}

${snippet_body}

${MARKER_END}"

  if [[ -f "${HOME_AGENTS}" ]]; then
    awk -v start="${MARKER_START}" -v end="${MARKER_END}" '
      $0 == start {skip=1; next}
      $0 == end {skip=0; next}
      skip != 1 {print}
    ' "${HOME_AGENTS}" > "${tmp_file}"
    {
      cat "${tmp_file}"
      printf "\n%s\n" "${block}"
    } > "${HOME_AGENTS}"
  else
    cat > "${HOME_AGENTS}" <<EOF
${block}
EOF
  fi
  rm -f "${tmp_file}"
fi

echo "Installed skills to ${SKILLS_DEST}"
if [[ "${INSTALL_HOME_AGENTS}" == "true" ]]; then
  echo "Updated ${HOME_AGENTS}"
else
  echo "Skipped home-level AGENTS install"
fi
echo "Restart Codex to pick up skill changes."
