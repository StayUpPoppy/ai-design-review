#!/usr/bin/env bash
# Create a compressed PostgreSQL backup for the Docker Compose deployment.
#
# Usage:
#   bash deploy/backup_postgres.sh
#
# Optional environment variables:
#   PROJECT_DIR=/opt/ai-design-review
#   BACKUP_DIR=/data/backups/ai-design-review
#   BACKUP_RETENTION_DAYS=30

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_DIR}/backups/postgres}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

if ! [[ "${BACKUP_RETENTION_DAYS}" =~ ^[0-9]+$ ]]; then
  echo "BACKUP_RETENTION_DAYS must be a non-negative integer." >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required but was not found in PATH." >&2
  exit 2
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is required but was not found." >&2
  exit 2
fi

mkdir -p "${BACKUP_DIR}"
cd "${PROJECT_DIR}"

timestamp="$(date +%F_%H%M%S)"
backup_file="${BACKUP_DIR}/ai_design_review_${timestamp}.sql.gz"
temporary_file="${backup_file}.partial"

cleanup() {
  rm -f "${temporary_file}"
}
trap cleanup EXIT

echo "Creating PostgreSQL backup: ${backup_file}"
"${COMPOSE[@]}" exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip -9 > "${temporary_file}"

if [[ ! -s "${temporary_file}" ]]; then
  echo "Backup failed: generated file is empty." >&2
  exit 1
fi

mv "${temporary_file}" "${backup_file}"
find "${BACKUP_DIR}" -type f -name 'ai_design_review_*.sql.gz' -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete

echo "Backup completed: ${backup_file}"
trap - EXIT
