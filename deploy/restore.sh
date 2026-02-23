#!/bin/bash

# FinLAN Restore Script
# Restores database and uploaded files from backup

BACKUP_DIR="/opt/finlan/backups"
DATA_DIR="/opt/finlan"
UPLOADS_DIR="/opt/finlan/uploads"

# Function to list available backups
list_backups() {
    echo "Available backups:"
    echo "=================="
    find "${BACKUP_DIR}" -maxdepth 1 -type d -name "finlan_backup_*" -printf "%T@ %p\n" | \
        sort -rn | \
        awk '{print NR". "$2" ("strftime("%Y-%m-%d %H:%M:%S", $1)")"}' | \
        sed "s|${BACKUP_DIR}/||"
}

# Check if backup directory exists
if [ ! -d "${BACKUP_DIR}" ]; then
    echo "✗ Backup directory not found: ${BACKUP_DIR}"
    exit 1
fi

# If no argument provided, list backups and exit
if [ -z "$1" ]; then
    list_backups
    echo ""
    echo "Usage: $0 <backup_name|latest|number>"
    echo "Examples:"
    echo "  $0 latest                    # Restore most recent backup"
    echo "  $0 finlan_backup_20260214_092544"
    echo "  $0 1                         # Restore backup #1 from list"
    exit 0
fi

# Determine backup path
if [ "$1" = "latest" ]; then
    RESTORE_PATH="${BACKUP_DIR}/latest"
elif [[ "$1" =~ ^[0-9]+$ ]]; then
    # User provided a number from the list
    BACKUP_NAME=$(find "${BACKUP_DIR}" -maxdepth 1 -type d -name "finlan_backup_*" -printf "%T@ %p\n" | \
        sort -rn | \
        awk "NR==$1 {print \$2}")
    if [ -z "${BACKUP_NAME}" ]; then
        echo "✗ Backup #$1 not found"
        list_backups
        exit 1
    fi
    RESTORE_PATH="${BACKUP_NAME}"
else
    RESTORE_PATH="${BACKUP_DIR}/$1"
fi

# Verify backup exists
if [ ! -d "${RESTORE_PATH}" ]; then
    echo "✗ Backup not found: ${RESTORE_PATH}"
    list_backups
    exit 1
fi

echo "Restoring from: $(basename ${RESTORE_PATH})"
echo "========================================"

# Confirm before proceeding
read -p "This will overwrite current data. Continue? (yes/no): " confirm
if [ "${confirm}" != "yes" ]; then
    echo "Restore cancelled"
    exit 0
fi

# Stop the service
echo "Stopping finlan service..."
sudo systemctl stop finlan

# Backup current state before restore (safety net)
SAFETY_BACKUP="${BACKUP_DIR}/pre_restore_$(date +%Y%m%d_%H%M%S)"
mkdir -p "${SAFETY_BACKUP}"
echo "Creating safety backup of current state..."
if [ -f "${DATA_DIR}/finlan.db" ]; then
    cp "${DATA_DIR}/finlan.db" "${SAFETY_BACKUP}/"
fi
if [ -d "${UPLOADS_DIR}" ]; then
    tar -czf "${SAFETY_BACKUP}/uploads.tar.gz" \
        -C "$(dirname ${UPLOADS_DIR})" "$(basename ${UPLOADS_DIR})" 2>/dev/null || true
fi

# Restore database
if [ -f "${RESTORE_PATH}/finlan.db" ]; then
    echo "Restoring database..."
    cp "${RESTORE_PATH}/finlan.db" "${DATA_DIR}/finlan.db"
    chown yrus:yrus "${DATA_DIR}/finlan.db"
    chmod 644 "${DATA_DIR}/finlan.db"
    echo "✓ Database restored"
else
    echo "✗ Database backup not found in ${RESTORE_PATH}"
fi

# Restore uploads (archive contains the 'uploads/' folder itself under app/)
if [ -f "${RESTORE_PATH}/uploads.tar.gz" ]; then
    echo "Restoring uploaded files..."
    rm -rf "${UPLOADS_DIR}"
    mkdir -p "$(dirname ${UPLOADS_DIR})"
    tar -xzf "${RESTORE_PATH}/uploads.tar.gz" -C "$(dirname ${UPLOADS_DIR})"
    chown -R yrus:yrus "${UPLOADS_DIR}"
    echo "✓ Uploads restored"
else
    echo "⚠ No uploads backup found"
fi

# Start the service
echo "Starting finlan service..."
sudo systemctl start finlan

# Wait and check status
sleep 2
if sudo systemctl is-active --quiet finlan; then
    echo "✓ Service started successfully"
else
    echo "✗ Service failed to start"
    sudo systemctl status finlan --no-pager
    exit 1
fi

echo ""
echo "✓ Restore completed successfully!"
echo "Safety backup saved at: ${SAFETY_BACKUP}"
