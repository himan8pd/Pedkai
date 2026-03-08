#!/usr/bin/env bash
# ============================================================================
# Pedkai — Backend VM Setup (Oracle Cloud Always Free ARM)
# ============================================================================
# Run this script on VM 1 (app server) after provisioning.
# Prerequisites: Ubuntu 22.04 aarch64, public IP assigned
#
# Usage: sudo bash setup-backend-vm.sh
# ============================================================================

set -euo pipefail

echo "=== Pedkai Backend VM Setup ==="

# --- 1. System updates ---
apt-get update && apt-get upgrade -y

# --- 2. Install Docker ---
apt-get install -y docker.io docker-compose-plugin
systemctl enable docker
systemctl start docker

# Add current user to docker group (re-login required)
usermod -aG docker "${SUDO_USER:-ubuntu}"

# --- 3. Install Caddy ---
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# --- 4. Create directories ---
mkdir -p /etc/caddy/certs
mkdir -p /srv/frontend

# --- 5. Install Node.js 20 (for frontend build) ---
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# --- 6. Configure firewall (iptables — OCI uses security lists too) ---
# Allow HTTP, HTTPS, and SSH
iptables -I INPUT -p tcp --dport 80 -j ACCEPT
iptables -I INPUT -p tcp --dport 443 -j ACCEPT
iptables -I INPUT -p tcp --dport 22 -j ACCEPT
# Save rules
apt-get install -y iptables-persistent
netfilter-persistent save

# --- 7. Set up anti-reclamation cron ---
(crontab -l 2>/dev/null || true; echo "0 */6 * * * dd if=/dev/urandom bs=1M count=100 | md5sum > /dev/null 2>&1") | sort -u | crontab -

echo ""
echo "=== Backend VM Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Upload Cloudflare origin certificate to /etc/caddy/certs/"
echo "     - origin.pem (certificate)"
echo "     - origin-key.pem (private key)"
echo "  2. Copy Caddyfile to /etc/caddy/Caddyfile"
echo "  3. Clone the Pedkai repo: git clone <repo-url> ~/Pedkai"
echo "  4. Create .env file in ~/Pedkai/ (use .env.cloud.example as template)"
echo "  5. Build and start: cd ~/Pedkai && docker compose -f docker-compose.cloud.yml up -d --build"
echo "  6. Copy frontend files: docker cp pedkai-frontend:/srv/frontend/. /srv/frontend/"
echo "  7. Start Caddy: sudo systemctl restart caddy"
echo "  8. Log out and back in for docker group to take effect"
