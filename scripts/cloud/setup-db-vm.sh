#!/usr/bin/env bash
# ============================================================================
# Pedkai — Database VM Setup (Oracle Cloud Always Free ARM)
# ============================================================================
# Run this script on VM 2 (database server) after provisioning.
# Prerequisites: Ubuntu 22.04 aarch64, 100 GB block volume attached
#
# Usage: sudo bash setup-db-vm.sh <block_volume_device> <db_password> <app_vm_private_ip>
# Example: sudo bash setup-db-vm.sh /dev/sdb MySecretPass123 10.0.1.2
# ============================================================================

set -euo pipefail

BLOCK_DEV="${1:?Usage: $0 <block_device> <db_password> <app_vm_private_ip>}"
DB_PASSWORD="${2:?Usage: $0 <block_device> <db_password> <app_vm_private_ip>}"
APP_VM_IP="${3:?Usage: $0 <block_device> <db_password> <app_vm_private_ip>}"

echo "=== Pedkai DB VM Setup ==="
echo "Block device: $BLOCK_DEV"
echo "App VM IP:    $APP_VM_IP"

# --- 1. System updates ---
apt-get update && apt-get upgrade -y

# --- 2. Add PostgreSQL 16 repo ---
apt-get install -y gnupg2 lsb-release curl rsync
echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/pgdg.gpg

# --- 3. Add TimescaleDB repo ---
echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/timescaledb.list
curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey | gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg

apt-get update

# --- 4. Install PostgreSQL 16 + extensions ---
apt-get install -y postgresql-16 postgresql-16-pgvector timescaledb-2-postgresql-16

# --- 5. Format and mount block volume ---
if ! blkid "$BLOCK_DEV" | grep -q ext4; then
    mkfs.ext4 "$BLOCK_DEV"
fi

mkdir -p /mnt/pgdata
mount "$BLOCK_DEV" /mnt/pgdata

# Add to fstab for persistence
BLOCK_UUID=$(blkid -s UUID -o value "$BLOCK_DEV")
if ! grep -q "$BLOCK_UUID" /etc/fstab; then
    echo "UUID=$BLOCK_UUID /mnt/pgdata ext4 defaults,nofail 0 2" >> /etc/fstab
fi

# --- 6. Move PostgreSQL data to block volume ---
systemctl stop postgresql
rsync -av /var/lib/postgresql/ /mnt/pgdata/
chown -R postgres:postgres /mnt/pgdata

# Update data_directory in postgresql.conf
PG_CONF="/etc/postgresql/16/main/postgresql.conf"
sed -i "s|data_directory = '.*'|data_directory = '/mnt/pgdata/16/main'|" "$PG_CONF"

# --- 7. Configure PostgreSQL ---
# Listen on all interfaces (VM 1 connects via private IP)
sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" "$PG_CONF"
sed -i "s/max_connections = 100/max_connections = 200/" "$PG_CONF"

# Add TimescaleDB to shared_preload_libraries
# Remove any existing line (commented or not) and append clean version
sed -i '/^#\?shared_preload_libraries/d' "$PG_CONF"
echo "shared_preload_libraries = 'timescaledb'" >> "$PG_CONF"

# --- 8. Open firewall for PostgreSQL from app VM ---
iptables -I INPUT 5 -p tcp -s "${APP_VM_IP}" --dport 5432 -j ACCEPT
apt-get install -y iptables-persistent
netfilter-persistent save

# --- 9. Configure pg_hba.conf — allow app VM only ---
PG_HBA="/etc/postgresql/16/main/pg_hba.conf"
echo "# Allow Pedkai app VM" >> "$PG_HBA"
echo "host    all    pedkai    ${APP_VM_IP}/32    md5" >> "$PG_HBA"

# --- 10. Start PostgreSQL ---
systemctl start postgresql
systemctl enable postgresql

# --- 11. Create user and databases ---
sudo -u postgres psql <<SQL
CREATE USER pedkai WITH PASSWORD '${DB_PASSWORD}';
CREATE DATABASE pedkai OWNER pedkai;
CREATE DATABASE pedkai_metrics OWNER pedkai;

\c pedkai
CREATE EXTENSION IF NOT EXISTS vector;

\c pedkai_metrics
CREATE EXTENSION IF NOT EXISTS timescaledb;
SQL

echo ""
echo "=== DB VM Setup Complete ==="
echo "PostgreSQL 16 + pgvector + TimescaleDB running on port 5432"
echo "Data directory: /mnt/pgdata/16/main"
echo "Databases: pedkai, pedkai_metrics"
echo "User: pedkai (password set)"
echo "Access: restricted to ${APP_VM_IP}"
