#!/usr/bin/env bash
# One-time VPS setup script.
# Run this once on a fresh Hetzner VPS (Ubuntu 22.04+).
# Usage: ssh root@your-server < scripts/setup-vps.sh
set -euo pipefail

echo "==> Installing Docker..."
curl -fsSL https://get.docker.com | sh
systemctl enable docker

echo "==> Creating deploy user..."
useradd -m -s /bin/bash -G docker deploy
mkdir -p /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
# Add your SSH public key here:
# echo "ssh-ed25519 AAAA..." >> /home/deploy/.ssh/authorized_keys
# chmod 600 /home/deploy/.ssh/authorized_keys
# chown -R deploy:deploy /home/deploy/.ssh

echo "==> Creating app directory..."
mkdir -p /opt/astraeus
chown deploy:deploy /opt/astraeus

echo "==> Setting up firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> Installing fail2ban..."
apt-get update -qq
apt-get install -y fail2ban
systemctl enable fail2ban

echo "==> Enabling unattended upgrades..."
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades

echo "==> Installing rclone (for backups)..."
curl -fsSL https://rclone.org/install.sh | bash

echo "==> Done!"
echo "    Next steps:"
echo "    1. Add your SSH public key to /home/deploy/.ssh/authorized_keys"
echo "    2. Copy compose.prod.yml and .env.prod to /opt/astraeus/"
echo "    3. Configure rclone for backup storage: rclone config"
