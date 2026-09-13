# Astraeus — Hosting & Deployment Guide

> Step-by-step guide to deploy Astraeus on a Hetzner VPS using Docker Compose.
> Beginner-friendly. Assumes you have basic terminal/SSH knowledge.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create a Hetzner Cloud Server](#2-create-a-hetzner-cloud-server)
3. [Initial Server Setup](#3-initial-server-setup)
4. [Install Docker](#4-install-docker)
5. [Set Up DNS & Cloudflare](#5-set-up-dns--cloudflare)
6. [Configure GitHub Container Registry](#6-configure-github-container-registry)
7. [Deploy the Application](#7-deploy-the-application)
8. [Configure Automated Backups](#8-configure-automated-backups)
9. [Set Up GitHub Actions CI/CD](#9-set-up-github-actions-cicd)
10. [Verify Everything Works](#10-verify-everything-works)
11. [Ongoing Maintenance](#11-ongoing-maintenance)
12. [Troubleshooting](#12-troubleshooting)
13. [Option B: Split Frontend to Vercel](#13-option-b-split-frontend-to-vercel)

---

## 1. Prerequisites

Before you start, make sure you have:

- [ ] A GitHub account with your Astraeus repo pushed
- [ ] A domain name (e.g., `astraeus.example.com`) — can buy from Namecheap, Cloudflare, etc.
- [ ] A Cloudflare account (free tier is fine)
- [ ] A Hetzner Cloud account — sign up at [hetzner.com/cloud](https://www.hetzner.com/cloud)
- [ ] An SSH key pair on your local machine
- [ ] API keys for services you use (Alpaca, Anthropic, OpenAI, etc.)

### Generate an SSH key (if you don't have one)

```bash
# On your local machine (Linux/Mac/WSL):
ssh-keygen -t ed25519 -C "your-email@example.com"

# This creates:
#   ~/.ssh/id_ed25519       (private key — NEVER share this)
#   ~/.ssh/id_ed25519.pub   (public key — this goes on the server)
```

On Windows without WSL, use PowerShell:
```powershell
ssh-keygen -t ed25519 -C "your-email@example.com"
# Keys go to C:\Users\YourName\.ssh\
```

---

## 2. Create a Hetzner Cloud Server

### 2.1 Log in to Hetzner Cloud Console

Go to [console.hetzner.cloud](https://console.hetzner.cloud) and create a new project (or use default).

### 2.2 Create a Server

Click **"Add Server"** and configure:

| Setting | Value |
|---------|-------|
| Location | Falkenstein (FSN1) or Nuremberg (NBG1) — cheapest EU locations |
| Image | Ubuntu 24.04 |
| Type | **CX31** (4 vCPU, 16GB RAM, 160GB disk) — €16.90/mo |
| SSH Key | Add your public key (`~/.ssh/id_ed25519.pub`) |
| Name | `astraeus-prod` |
| Backups | Enable (adds ~20% to cost, worth it) |

> **Why CX31?** 16GB RAM is enough for all services including NLP models. If you hit memory limits later, upgrade to CX51 (32GB) — takes ~1 minute via the console.

### 2.3 Note Your Server IP

After creation, Hetzner shows your server's IPv4 address. Note it down:
```
Server IP: xxx.xxx.xxx.xxx
```

---

## 3. Initial Server Setup

### 3.1 SSH into the Server

```bash
ssh root@xxx.xxx.xxx.xxx
```

### 3.2 Run the Setup Script

The project includes a setup script at `scripts/setup-vps.sh`. You can run it directly:

```bash
# From your local machine, pipe the script to the server:
ssh root@xxx.xxx.xxx.xxx < scripts/setup-vps.sh
```

Or manually do what the script does:

```bash
# Update system
apt-get update && apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker

# Create a deploy user (don't run containers as root)
useradd -m -s /bin/bash -G docker deploy
mkdir -p /home/deploy/.ssh
chmod 700 /home/deploy/.ssh

# Add your SSH public key for the deploy user
echo "ssh-ed25519 AAAA... your-email@example.com" >> /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

# Create the app directory
mkdir -p /opt/astraeus
chown deploy:deploy /opt/astraeus

# Set up firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Install fail2ban (brute-force protection)
apt-get install -y fail2ban
systemctl enable fail2ban

# Enable automatic security updates
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades

# Install rclone (for backups to object storage)
curl -fsSL https://rclone.org/install.sh | bash
```

### 3.3 Disable Root SSH Login (Security Hardening)

```bash
# Edit SSH config
nano /etc/ssh/sshd_config

# Change these lines:
#   PermitRootLogin no
#   PasswordAuthentication no

# Restart SSH
systemctl restart sshd
```

### 3.4 Verify Deploy User Access

From your local machine, test:
```bash
ssh deploy@xxx.xxx.xxx.xxx
```

You should get a shell. From now on, always use the `deploy` user.

---

## 4. Install Docker

If you ran the setup script, Docker is already installed. Verify:

```bash
ssh deploy@xxx.xxx.xxx.xxx
docker --version
# Docker version 27.x.x
docker compose version
# Docker Compose version v2.x.x
```

If Docker Compose isn't available as a plugin:
```bash
# As root:
apt-get install -y docker-compose-plugin
```

---

## 5. Set Up DNS & Cloudflare

### 5.1 Add Your Domain to Cloudflare

1. Sign up at [cloudflare.com](https://www.cloudflare.com)
2. Click "Add a Site" → enter your domain
3. Select the **Free** plan
4. Cloudflare gives you nameservers — update them at your domain registrar

### 5.2 Create DNS Records

In Cloudflare DNS settings, add:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `astraeus` (or `@` for root) | `xxx.xxx.xxx.xxx` | Proxied (orange cloud) |

> **Why proxied?** Cloudflare provides free DDoS protection and hides your server IP.

### 5.3 SSL/TLS Settings

In Cloudflare → SSL/TLS:
- Set encryption mode to **Full (strict)**
- This works because Caddy (our reverse proxy) auto-provisions real certificates

### 5.4 Wait for DNS Propagation

DNS changes can take 5 minutes to 48 hours. Check with:
```bash
nslookup astraeus.example.com
# Should return your server IP (or Cloudflare's proxy IP)
```

---

## 6. Configure GitHub Container Registry

Your Docker images are built by GitHub Actions and pushed to GitHub Container Registry (GHCR). The deploy workflow pulls them on the VPS.

### 6.1 Make Sure GHCR Packages Are Accessible

By default, GHCR packages from private repos require authentication. On the VPS:

```bash
ssh deploy@xxx.xxx.xxx.xxx

# Create a GitHub Personal Access Token (PAT) with `read:packages` scope
# Go to: GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
# Create token with scope: read:packages

# Log in to GHCR on the VPS
echo "YOUR_GITHUB_PAT" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

This saves credentials to `/home/deploy/.docker/config.json` so `docker compose pull` works.

### 6.2 Verify Image Access

```bash
docker pull ghcr.io/YOUR_GITHUB_USERNAME/astraeus-api:main
# Should succeed
```

---

## 7. Deploy the Application

### 7.1 Copy Configuration Files to the Server

From your local machine (in the Astraeus repo root):

```bash
# Copy the production compose file
scp infra/docker/compose.prod.yml deploy@xxx.xxx.xxx.xxx:/opt/astraeus/compose.prod.yml

# Copy the Caddyfile
ssh deploy@xxx.xxx.xxx.xxx "mkdir -p /opt/astraeus/caddy"
scp infra/docker/caddy/Caddyfile deploy@xxx.xxx.xxx.xxx:/opt/astraeus/caddy/Caddyfile

# Copy postgres init scripts
ssh deploy@xxx.xxx.xxx.xxx "mkdir -p /opt/astraeus/postgres"
scp infra/docker/postgres/init.sql deploy@xxx.xxx.xxx.xxx:/opt/astraeus/postgres/init.sql
scp infra/docker/postgres/timescale.sh deploy@xxx.xxx.xxx.xxx:/opt/astraeus/postgres/timescale.sh

# Copy the backup script
ssh deploy@xxx.xxx.xxx.xxx "mkdir -p /opt/astraeus/scripts"
scp scripts/backup-db.sh deploy@xxx.xxx.xxx.xxx:/opt/astraeus/scripts/backup-db.sh
ssh deploy@xxx.xxx.xxx.xxx "chmod +x /opt/astraeus/scripts/backup-db.sh"
```

### 7.2 Create the Production Environment File

SSH into the server and create `.env.prod`:

```bash
ssh deploy@xxx.xxx.xxx.xxx
cd /opt/astraeus
nano .env.prod
```

Fill in your values (use the template from `infra/docker/.env.prod.example`):

```env
# Domain — must match your DNS record
DOMAIN=astraeus.example.com
TAG=main
GITHUB_OWNER=your-github-username

# Database — use a strong random password
DB_USER=astraeus
DB_PASSWORD=your-strong-random-password-here

# MinIO — use a different strong password
MINIO_USER=astraeus
MINIO_PASSWORD=another-strong-random-password

# Auth — generate with: openssl rand -hex 32
ASTRAEUS_AUTH_JWT_SECRET=your-64-char-random-hex-string
NEXTAUTH_SECRET=same-value-as-jwt-secret

# Market Data API Keys
ASTRAEUS_MD_ALPACA_API_KEY=your-alpaca-key
ASTRAEUS_MD_ALPACA_API_SECRET=your-alpaca-secret

# LLM API Keys
ASTRAEUS_LLM_ANTHROPIC_API_KEY=sk-ant-...
ASTRAEUS_LLM_OPENAI_API_KEY=sk-...
```

> **Generating strong passwords:**
> ```bash
> # On your local machine or the server:
> openssl rand -hex 32
> ```

### 7.3 Update the Caddyfile with Your Domain

The Caddyfile uses the `$DOMAIN` environment variable. Make sure it's set in `.env.prod` (already done above). However, Caddy reads its config directly, so you need to hardcode your domain in the Caddyfile:

```bash
nano /opt/astraeus/caddy/Caddyfile
```

Replace `{$DOMAIN}` with your actual domain:

```
astraeus.example.com {
    # Frontend
    handle /* {
        reverse_proxy web:3000
    }

    # API
    handle /api/* {
        reverse_proxy api:8000
    }

    # WebSocket
    handle /ws/* {
        reverse_proxy api:8000
    }

    # OMS API
    handle /oms/* {
        reverse_proxy oms:8001
    }
}
```

### 7.4 Pull and Start All Services

```bash
cd /opt/astraeus
docker compose -f compose.prod.yml pull
docker compose -f compose.prod.yml up -d
```

### 7.5 Check That Everything Started

```bash
docker compose -f compose.prod.yml ps
```

You should see all services running:
```
NAME                  STATUS
astraeus-api-1        Up (healthy)
astraeus-oms-1        Up
astraeus-workers-1    Up
astraeus-web-1        Up
astraeus-postgres-1   Up (healthy)
astraeus-redis-1      Up (healthy)
astraeus-minio-1      Up (healthy)
astraeus-caddy-1      Up
```

### 7.6 Check Logs If Something Fails

```bash
# All services
docker compose -f compose.prod.yml logs

# Specific service
docker compose -f compose.prod.yml logs api
docker compose -f compose.prod.yml logs postgres

# Follow logs in real-time
docker compose -f compose.prod.yml logs -f api
```

### 7.7 Run Database Migrations

The first time you deploy, you need to run Alembic migrations:

```bash
docker compose -f compose.prod.yml exec api alembic upgrade head
```

---

## 8. Configure Automated Backups

### 8.1 Set Up Hetzner Object Storage

1. In Hetzner Cloud Console → **Object Storage** → Create a bucket
2. Name it `astraeus-backups`
3. Note the S3 endpoint, access key, and secret key

### 8.2 Configure rclone on the VPS

```bash
ssh deploy@xxx.xxx.xxx.xxx
rclone config
```

Follow the interactive prompts:
```
n) New remote
name> hetzner-s3
Storage> s3
provider> Other
env_auth> false
access_key_id> YOUR_HETZNER_S3_ACCESS_KEY
secret_access_key> YOUR_HETZNER_S3_SECRET_KEY
endpoint> fsn1.your-objectstorage.com
```

Test it:
```bash
rclone ls hetzner-s3:astraeus-backups
# Should return empty (no backups yet)
```

### 8.3 Test the Backup Script

```bash
/opt/astraeus/scripts/backup-db.sh
```

Check that the backup appeared:
```bash
rclone ls hetzner-s3:astraeus-backups/daily/
# Should show: astraeus-YYYYMMDD-HHMMSS.dump
```

### 8.4 Set Up Daily Cron Job

```bash
crontab -e
```

Add this line (runs daily at 3:00 AM server time):
```
0 3 * * * /opt/astraeus/scripts/backup-db.sh >> /var/log/astraeus-backup.log 2>&1
```

### 8.5 Test a Restore (Do This Now)

It's critical to verify backups actually work:

```bash
# Download a backup
rclone copy hetzner-s3:astraeus-backups/daily/astraeus-YYYYMMDD-HHMMSS.dump /tmp/

# Restore (this will overwrite current data — only do on a test DB!)
docker exec -i astraeus-postgres-1 pg_restore -U astraeus -d astraeus --clean /tmp/astraeus-YYYYMMDD-HHMMSS.dump
```

---

## 9. Set Up GitHub Actions CI/CD

The repo already has a deploy workflow at `.github/workflows/deploy.yml`. It:
1. Builds Docker images for `api`, `workers`, and `web`
2. Pushes them to GHCR
3. SSHs into your VPS and runs `docker compose pull && up -d`

### 9.1 Add Repository Secrets

Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret Name | Value |
|-------------|-------|
| `VPS_HOST` | Your server IP (e.g., `xxx.xxx.xxx.xxx`) |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | Contents of your private key (`~/.ssh/id_ed25519`) |

### 9.2 Create a Production Environment

Go to **Settings** → **Environments** → **New environment**:
- Name: `production`
- (Optional) Add required reviewers if you want manual approval before deploys

### 9.3 Test the Pipeline

Push a commit to `main`:
```bash
git commit --allow-empty -m "test: trigger deploy"
git push origin main
```

Watch the Actions tab — it should build images and deploy to your VPS.

### 9.4 Manual Deploy (Without CI)

If you need to deploy without pushing to main:

```bash
# From your local machine:
VPS_HOST=xxx.xxx.xxx.xxx ./scripts/deploy-vps.sh
```

Or trigger the workflow manually: GitHub → Actions → Deploy → "Run workflow"

---

## 10. Verify Everything Works

### 10.1 Check the API

```bash
curl https://astraeus.example.com/api/health
# Should return: {"status": "ok", ...}
```

### 10.2 Check the Frontend

Open `https://astraeus.example.com` in your browser. You should see the Astraeus web UI.

### 10.3 Check WebSocket Connectivity

Open browser dev tools → Network → WS tab. Navigate to a page that uses real-time data. You should see WebSocket connections to `/ws/...`.

### 10.4 Check Resource Usage

```bash
ssh deploy@xxx.xxx.xxx.xxx

# Memory usage
free -h

# Per-container resource usage
docker stats --no-stream

# Disk usage
df -h
```

**Expected memory usage (approximate):**
| Service | RAM |
|---------|-----|
| PostgreSQL + TimescaleDB | 2–4 GB |
| Workers (NLP models loaded) | 2–3 GB |
| API | 300–500 MB |
| OMS | 200–300 MB |
| Web (Next.js) | 200–400 MB |
| Redis | 100–300 MB |
| MinIO | 100–200 MB |
| Caddy | ~20 MB |
| **Total** | **~6–9 GB** |

On a 16GB VPS, you have comfortable headroom.

---

## 11. Ongoing Maintenance

### 11.1 Updating the Application

Just push to `main`. GitHub Actions handles the rest. Or manually:

```bash
ssh deploy@xxx.xxx.xxx.xxx
cd /opt/astraeus
docker compose -f compose.prod.yml pull
docker compose -f compose.prod.yml up -d --remove-orphans
docker image prune -f
```

### 11.2 Viewing Logs

```bash
# Last 100 lines from API
docker compose -f compose.prod.yml logs --tail=100 api

# Follow all logs
docker compose -f compose.prod.yml logs -f

# Search for errors
docker compose -f compose.prod.yml logs api 2>&1 | grep -i error
```

### 11.3 Running Database Migrations

After deploying code that includes new migrations:

```bash
docker compose -f compose.prod.yml exec api alembic upgrade head
```

### 11.4 Restarting a Single Service

```bash
docker compose -f compose.prod.yml restart api
```

### 11.5 Upgrading the VPS

If you need more resources:

1. Go to Hetzner Cloud Console → your server → **Rescale**
2. Choose CX51 (32GB) or higher
3. Server restarts in ~1 minute
4. All data and Docker volumes are preserved

### 11.6 System Updates

```bash
ssh deploy@xxx.xxx.xxx.xxx
sudo apt-get update && sudo apt-get upgrade -y

# Reboot if kernel was updated
sudo reboot
```

Unattended-upgrades handles security patches automatically, but check monthly for major updates.

### 11.7 Monitoring Disk Space

```bash
# Check overall disk
df -h /

# Check Docker disk usage
docker system df

# Clean up old images/containers
docker system prune -a --volumes
# WARNING: --volumes removes unused volumes. Only use if you're sure.
```

---

## 12. Troubleshooting

### Container won't start

```bash
# Check logs for the failing container
docker compose -f compose.prod.yml logs <service-name>

# Check if it's a resource issue
docker stats --no-stream
free -h
```

### Database connection refused

```bash
# Check if postgres is healthy
docker compose -f compose.prod.yml ps postgres

# Check postgres logs
docker compose -f compose.prod.yml logs postgres

# Verify credentials
docker compose -f compose.prod.yml exec postgres psql -U astraeus -d astraeus -c "SELECT 1;"
```

### Caddy not serving HTTPS

```bash
# Check Caddy logs
docker compose -f compose.prod.yml logs caddy

# Common issues:
# - Domain DNS not pointing to server yet
# - Port 80/443 blocked by firewall
# - Caddyfile syntax error
```

If using Cloudflare proxy, make sure SSL mode is "Full (strict)" — Caddy provisions its own cert, and Cloudflare needs to trust it.

### Out of memory (OOM kills)

```bash
# Check which container was killed
dmesg | grep -i oom

# Check current memory
docker stats --no-stream

# Solutions:
# 1. Upgrade VPS (CX31 → CX51)
# 2. Reduce worker memory limit in compose.prod.yml
# 3. Enable swap (temporary fix):
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Deploy fails via GitHub Actions

1. Check the Actions tab for error messages
2. Common issues:
   - SSH key mismatch → re-add `VPS_SSH_KEY` secret
   - Server unreachable → check if VPS is running, firewall allows SSH
   - Docker pull fails → re-authenticate GHCR on VPS

### Redis connection issues

```bash
docker compose -f compose.prod.yml exec redis redis-cli ping
# Should return: PONG

# Check memory usage
docker compose -f compose.prod.yml exec redis redis-cli info memory
```

---

## 13. Option B: Split Frontend to Vercel

If you want faster frontend iteration with preview deploys per PR, deploy the Next.js frontend to Vercel separately.

### 13.1 Connect Vercel to Your Repo

1. Go to [vercel.com](https://vercel.com) → "Add New Project"
2. Import your GitHub repo
3. Set the **Root Directory** to `apps/web`
4. Set the **Framework Preset** to Next.js

### 13.2 Configure Environment Variables in Vercel

In Vercel project settings → Environment Variables:

| Variable | Value |
|----------|-------|
| `API_URL` | `https://astraeus.example.com` |
| `NEXTAUTH_URL` | `https://app.astraeus.example.com` (or your Vercel domain) |
| `NEXTAUTH_SECRET` | Same JWT secret as backend |

### 13.3 Update DNS

Add a CNAME record in Cloudflare:

| Type | Name | Content |
|------|------|---------|
| CNAME | `app` | `cname.vercel-dns.com` |

### 13.4 Update Backend CORS

Make sure your API allows requests from the Vercel domain. Update CORS settings in the API configuration.

### 13.5 Remove Web from Docker Compose

On the VPS, you no longer need the `web` service. Edit `compose.prod.yml`:
- Remove the `web` service block
- Update Caddy to only proxy API/OMS/WS (remove the frontend `handle /*` block)

This saves ~512MB RAM on the VPS and gives you instant frontend deploys via Vercel.

---

## Quick Reference

### SSH Access
```bash
ssh deploy@xxx.xxx.xxx.xxx
```

### Deploy
```bash
cd /opt/astraeus && docker compose -f compose.prod.yml pull && docker compose -f compose.prod.yml up -d
```

### Logs
```bash
docker compose -f compose.prod.yml logs -f <service>
```

### Restart
```bash
docker compose -f compose.prod.yml restart <service>
```

### Backup (manual)
```bash
/opt/astraeus/scripts/backup-db.sh
```

### Database Shell
```bash
docker compose -f compose.prod.yml exec postgres psql -U astraeus -d astraeus
```

### Redis Shell
```bash
docker compose -f compose.prod.yml exec redis redis-cli
```

---

## Cost Summary

| Component | Monthly Cost |
|-----------|-------------|
| Hetzner CX31 (16GB VPS) | ~$18 |
| Hetzner Backups (20% of server) | ~$4 |
| Hetzner Object Storage | ~$2 |
| Cloudflare (free tier) | $0 |
| Domain renewal | ~$1 (amortized) |
| LLM APIs (Anthropic/OpenAI) | $10–50 |
| **Total** | **~$35–75/mo** |

Upgrade to CX51 (32GB) adds ~$17/mo if needed.
