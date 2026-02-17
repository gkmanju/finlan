# FinLAN Backup System

## Overview
Automated daily backups of the FinLAN financial portal, including:
- SQLite database (finlan.db)
- Uploaded receipt files

## Backup Storage
- **Location**: `/opt/finlan/backups/`
- **Retention**: 30 days
- **Schedule**: Daily at 2:00 AM
- **Naming**: `finlan_backup_YYYYMMDD_HHMMSS/`
- **Symlink**: `latest` → most recent backup

## Backup Contents
Each backup folder contains:
- `finlan.db` - SQLite database backup
- `uploads.tar.gz` - Compressed receipt files

## Usage

### Manual Backup
```bash
sudo /opt/finlan/deploy/backup.sh
```

### List Available Backups
```bash
sudo /opt/finlan/deploy/restore.sh
```

### Restore from Latest Backup
```bash
sudo /opt/finlan/deploy/restore.sh latest
```

### Restore from Specific Backup
```bash
sudo /opt/finlan/deploy/restore.sh finlan_backup_20260214_092544
```

### Restore by Number
```bash
# First, list backups to see numbers
sudo /opt/finlan/deploy/restore.sh

# Then restore by number (e.g., backup #1)
sudo /opt/finlan/deploy/restore.sh 1
```

## Automated Schedule
Cron job runs daily at 2:00 AM:
```cron
0 2 * * * /opt/finlan/deploy/backup.sh >> /opt/finlan/backups/backup.log 2>&1
```

## Monitoring
View backup logs:
```bash
tail -f /opt/finlan/backups/backup.log
```

Check last backup:
```bash
ls -lh /opt/finlan/backups/latest/
```

## Disk Space Management
- Automatic cleanup: Backups older than 30 days are deleted
- Current backup size: ~85MB per backup
- 30-day retention: ~2.5GB storage needed

## Safety Features
1. **Pre-restore backup**: Automatic safety backup before restore
2. **Service management**: Auto-stop/start service during restore
3. **Verification**: Checks database and file integrity
4. **Confirmation prompt**: Prevents accidental restores

## Troubleshooting

### Check if cron job is running
```bash
sudo crontab -l | grep backup
```

### View recent backup history
```bash
ls -lht /opt/finlan/backups/ | head -10
```

### Manually verify backup
```bash
sqlite3 /opt/finlan/backups/latest/finlan.db "SELECT COUNT(*) FROM receipts;"
tar -tzf /opt/finlan/backups/latest/uploads.tar.gz | wc -l
```

### Test restore in dry-run mode
```bash
# View what would be restored
ls -lh /opt/finlan/backups/latest/
```

## Off-site Backup (Optional)
For additional protection, you can:

### Option 1: Network Share
Add to backup.sh:
```bash
# Copy to network share after backup
cp -r "${BACKUP_PATH}" /mnt/nas/finlan_backups/
```

### Option 2: Cloud Sync (rclone)
```bash
# Install rclone
sudo apt install rclone

# Configure cloud provider
rclone config

# Add to backup.sh
rclone sync "${BACKUP_DIR}" remote:finlan_backups --exclude "*.log"
```

### Option 3: Windows Share
From Windows machine (your OneDrive location):
```powershell
# Schedule task to pull backups daily
scp -r <USER>@<SERVER_IP>:/opt/finlan/backups/latest <YOUR_PATH>\OneDrive\FinLAN_Backups\
```

## Security Notes
- Backups contain sensitive financial data
- Ensure `/opt/finlan/backups/` has restricted permissions (700)
- Do not store backups in publicly accessible locations
- If using off-site backups, use encryption (e.g., rclone crypt)
