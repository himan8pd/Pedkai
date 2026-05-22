#!/usr/bin/env bash
# ============================================================================
# Pedkai — Backend VM Setup (Oracle Cloud Always Free ARM)
# ============================================================================
# Run this script on VM 1 (app server) after provisioning.
# Prerequisites: Ubuntu 22.04 aarch64, public IP assigned
#
# Usage: sudo bash setup-backend-vm.sh
#
# After this script, all services (Caddy, Ollama, FastAPI, Kafka, frontend)
# run inside Docker Compose — no native service installs required.
# ============================================================================

set -euo pipefail

echo "=== Pedkai Backend VM Setup ==="

# --- 1. System updates ---
apt-get update && apt-get upgrade -y

# --- 2. Install Docker (official repo — Ubuntu minimal lacks docker-compose-plugin) ---
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker
systemctl start docker

# Add current user to docker group (re-login required)
usermod -aG docker "${SUDO_USER:-ubuntu}"

# --- 3. Create required host directories ---
mkdir -p /etc/caddy/certs    # Cloudflare origin TLS certs (uploaded manually)
mkdir -p /opt/tslam           # TSLAM GGUF model file (uploaded manually)

# --- 4. Configure firewall (iptables — OCI uses security lists too) ---
apt-get install -y iptables-persistent
iptables -I INPUT -p tcp --dport 80 -j ACCEPT
iptables -I INPUT -p tcp --dport 443 -j ACCEPT
iptables -I INPUT -p tcp --dport 22 -j ACCEPT
netfilter-persistent save

# --- 5. Set up anti-reclamation cron (Oracle reclaims idle Always Free VMs) ---
(crontab -l 2>/dev/null || true; echo "0 */6 * * * dd if=/dev/urandom bs=1M count=100 | md5sum > /dev/null 2>&1") | sort -u | crontab -

echo ""
echo "=== Backend VM Setup Complete ==="
echo ""
echo "Next steps:"
echo ""
echo "  1. Upload Cloudflare origin certificate to /etc/caddy/certs/"
echo "       origin.pem       (certificate)"
echo "       origin-key.pem   (private key)"
echo ""
echo "  2. Upload TSLAM GGUF model:"
echo "       scp /path/to/tslam-mini-2b-q4km.gguf ubuntu@<vm-ip>:/opt/tslam/"
echo ""
echo "  3. Clone the Pedkai repo:"
echo "       git clone <repo-url> ~/Pedkai"
echo ""
echo "  4. Create .env file:"
echo "       cp ~/Pedkai/.env.cloud.example ~/Pedkai/.env"
echo "       # Edit .env — fill in DB IPs, passwords, API keys"
echo ""
echo "  5. Start the full stack:"
echo "       cd ~/Pedkai"
echo "       docker compose -f docker-compose.cloud.yml up -d --build"
echo ""
echo "  6. Log out and back in for docker group to take effect."
