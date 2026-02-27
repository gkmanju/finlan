#!/bin/bash

# FinLAN Automated Backup Script
# Backs up database and uploaded files

BACKUP_DIR="/opt/finlan/backups"
DATA_DIR="/opt/finlan"
UPLOADS_DIR="/opt/finlan/uploads"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="finlan_backup_${TIMESTAMP}"
RETENTION_DAYS=30

# NAS Configuration (set these in environment or override here)
NAS_IP="${NAS_IP:-192.168.1.200}"
NAS_USER="${NAS_USER:-}"
NAS_SSH_KEY="${NAS_SSH_KEY:-$HOME/.ssh/id_rsa}"
NAS_BACKUP_DIR="${NAS_BACKUP_DIR:-/volume1/backups/finlan_backups}"

if [ -z "$NAS_USER" ]; then
    echo "ERROR: NAS_USER environment variable must be set" >&2
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

# Create timestamped backup folder
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"
mkdir -p "${BACKUP_PATH}"

echo "Starting backup at $(date)"

# Backup SQLite database
if [ -f "${DATA_DIR}/finlan.db" ]; then
    echo "Backing up database..."
    sqlite3 "${DATA_DIR}/finlan.db" ".backup '${BACKUP_PATH}/finlan.db'"
    if [ $? -eq 0 ]; then
        echo "✓ Database backed up successfully"
    else
        echo "✗ Database backup failed"
        exit 1
    fi
else
    echo "✗ Database not found at ${DATA_DIR}/finlan.db"
    exit 1
fi

# Backup uploaded files (receipts + tax_docs subdirs)
if [ -d "${UPLOADS_DIR}" ]; then
    echo "Backing up uploaded files..."
    tar -czf "${BACKUP_PATH}/uploads.tar.gz" -C "$(dirname ${UPLOADS_DIR})" "$(basename ${UPLOADS_DIR})"
    if [ $? -eq 0 ]; then
        echo "✓ Uploads backed up successfully"
        RECEIPT_COUNT=$(find "${UPLOADS_DIR}" -maxdepth 2 -not -path '*/tax_docs/*' -type f | wc -l)
        TAX_COUNT=$(find "${UPLOADS_DIR}/tax_docs" -type f 2>/dev/null | wc -l)
        echo "  Receipts: ${RECEIPT_COUNT}  Tax docs: ${TAX_COUNT}"
    else
        echo "✗ Uploads backup failed"
    fi
else
    echo "⚠ Uploads directory not found at ${UPLOADS_DIR}"
fi

# Backup docs (tax worksheets - NAS only, not in git)
DOCS_DIR="/opt/finlan/docs"
if [ -d "${DOCS_DIR}" ]; then
    echo "Backing up docs..."
    tar -czf "${BACKUP_PATH}/docs.tar.gz" -C "$(dirname ${DOCS_DIR})" "$(basename ${DOCS_DIR})"
    if [ $? -eq 0 ]; then
        DOC_COUNT=$(find "${DOCS_DIR}" -type f | wc -l)
        echo "✓ Docs backed up: ${DOC_COUNT} files"
    else
        echo "✗ Docs backup failed"
    fi
fi

# Write a manifest of what's in this backup
cat > "${BACKUP_PATH}/manifest.txt" <<EOF
FinLAN Backup Manifest
======================
Timestamp : ${TIMESTAMP}
Hostname  : $(hostname)
DB size   : $(du -sh ${DATA_DIR}/finlan.db 2>/dev/null | cut -f1 || echo 'n/a')
Receipts  : ${RECEIPT_COUNT:-0} files
Tax docs  : ${TAX_COUNT:-0} files
Docs      : ${DOC_COUNT:-0} files
EOF
echo "✓ Manifest written"

# Get backup size
BACKUP_SIZE=$(du -sh "${BACKUP_PATH}" | cut -f1)
echo "✓ Backup completed: ${BACKUP_SIZE}"

# Create latest symlink
ln -sf "${BACKUP_PATH}" "${BACKUP_DIR}/latest"

# Clean up old backups (keep last 30 days)
echo "Cleaning up old backups (keeping last ${RETENTION_DAYS} days)..."
find "${BACKUP_DIR}" -maxdepth 1 -type d -name "finlan_backup_*" -mtime +${RETENTION_DAYS} -exec rm -rf {} \;

# Count remaining backups
BACKUP_COUNT=$(find "${BACKUP_DIR}" -maxdepth 1 -type d -name "finlan_backup_*" | wc -l)
echo "✓ Total backups: ${BACKUP_COUNT}"

# Sync to NAS via SSH/rsync
if [ -n "${NAS_IP}" ]; then
    echo ""
    echo "Syncing to NAS (${NAS_IP})..."

    # Ensure backup dir exists on NAS
    ssh -i "${NAS_SSH_KEY}" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no \
        "${NAS_USER}@${NAS_IP}" "mkdir -p ${NAS_BACKUP_DIR}"

    if [ $? -eq 0 ]; then
        # Rsync over SSH - exclude symlinks (NAS may not support them)
        rsync -av --delete --no-links \
            -e "ssh -i ${NAS_SSH_KEY} -o BatchMode=yes -o StrictHostKeyChecking=no" \
            "${BACKUP_DIR}/" "${NAS_USER}@${NAS_IP}:${NAS_BACKUP_DIR}/"

        if [ $? -eq 0 ]; then
            NAS_SIZE=$(ssh -i "${NAS_SSH_KEY}" -o BatchMode=yes -o StrictHostKeyChecking=no \
                "${NAS_USER}@${NAS_IP}" "du -sh ${NAS_BACKUP_DIR}" | cut -f1)
            echo "✓ Synced to NAS: ${NAS_SIZE}"
        else
            echo "✗ NAS rsync failed"
        fi
    else
        echo "✗ Cannot connect to NAS at ${NAS_IP}"
    fi
fi

echo "Backup completed at $(date)"
