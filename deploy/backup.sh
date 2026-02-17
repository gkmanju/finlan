#!/bin/bash

# FinLAN Automated Backup Script
# Backs up database and uploaded files

BACKUP_DIR="/opt/finlan/backups"
DATA_DIR="/opt/finlan/data"
UPLOADS_DIR="/opt/finlan/app/uploads"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="finlan_backup_${TIMESTAMP}"
RETENTION_DAYS=30

# NAS Configuration
NAS_IP="<NAS_IP>"
NAS_USER="<NAS_USER>"
NAS_SHARE="home"
NAS_MOUNT="/mnt/nas_backup"
NAS_BACKUP_DIR="${NAS_MOUNT}/<NAS_USER>/finlan_backups"

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

# Backup uploaded files
if [ -d "${UPLOADS_DIR}" ]; then
    echo "Backing up uploaded files..."
    tar -czf "${BACKUP_PATH}/uploads.tar.gz" -C "${UPLOADS_DIR}" .
    if [ $? -eq 0 ]; then
        echo "✓ Uploads backed up successfully"
        UPLOAD_COUNT=$(ls -1 "${UPLOADS_DIR}" | wc -l)
        echo "  Files backed up: ${UPLOAD_COUNT}"
    else
        echo "✗ Uploads backup failed"
    fi
else
    echo "⚠ Uploads directory not found"
fi

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

# Sync to NAS
if [ -n "${NAS_IP}" ]; then
    echo ""
    echo "Syncing to NAS (${NAS_IP})..."
    
    # Create mount point if needed
    sudo mkdir -p "${NAS_MOUNT}"
    
    # Check if already mounted
    if mountpoint -q "${NAS_MOUNT}"; then
        echo "NAS already mounted"
    else
        # Prompt for password if not in cron (interactive mode)
        if [ -t 0 ]; then
            echo "Enter NAS password for ${NAS_USER}:"
            read -s NAS_PASSWORD
            echo "${NAS_PASSWORD}" | sudo mount -t cifs "//${NAS_IP}/${NAS_SHARE}" "${NAS_MOUNT}" \
                -o username="${NAS_USER}",password="${NAS_PASSWORD}",uid=$(id -u),gid=$(id -g)
        else
            # In cron mode, try credentials file
            if [ -f /opt/finlan/.nas_credentials ]; then
                sudo mount -t cifs "//${NAS_IP}/${NAS_SHARE}" "${NAS_MOUNT}" \
                    -o credentials=/opt/finlan/.nas_credentials,uid=$(id -u),gid=$(id -g)
            else
                echo "⚠ NAS credentials file not found, skipping NAS sync"
                echo "Backup completed at $(date)"
                exit 0
            fi
        fi
    fi
    
    if mountpoint -q "${NAS_MOUNT}"; then
        # Create backup directory on NAS
        sudo mkdir -p "${NAS_BACKUP_DIR}"
        
        # Sync backup to NAS (exclude symlinks since CIFS doesn't support them)
        sudo rsync -a --delete --no-links "${BACKUP_DIR}/" "${NAS_BACKUP_DIR}/"
        
        if [ $? -eq 0 ]; then
            NAS_SIZE=$(sudo du -sh "${NAS_BACKUP_DIR}" | cut -f1)
            echo "✓ Synced to NAS: ${NAS_SIZE}"
            
            # Unmount (if we mounted it)
            if [ -t 0 ]; then
                sudo umount "${NAS_MOUNT}"
            fi
        else
            echo "✗ NAS sync failed"
        fi
    else
        echo "✗ Failed to mount NAS"
    fi
fi

echo "Backup completed at $(date)"
