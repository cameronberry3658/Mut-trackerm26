#!/bin/bash
# ============================================================
# MUT Tracker AWS Deployment Script
# Run on Amazon Linux 2023 EC2 after SSH'ing in
# ============================================================

set -e
echo "=== [1/8] Updating system ==="
sudo dnf update -y

echo "=== [2/8] Installing dependencies ==="
sudo dnf install -y python3 python3-pip git httpd mod_ssl openssl

echo "=== [3/8] Creating app directory ==="
sudo mkdir -p /opt/muttracker
sudo chown -R ec2-user:ec2-user /opt/muttracker
cd /opt/muttracker

echo "=== [4/8] Installing Python packages ==="
pip3 install --user flask requests beautifulsoup4

echo "=== [5/8] Generating self-signed TLS certificate ==="
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/pki/tls/private/muttracker.key \
  -out /etc/pki/tls/certs/muttracker.crt \
  -subj "/C=US/ST=NC/L=Pembroke/O=UNCP/CN=muttracker.local"

echo "=== [6/8] Configuring Apache reverse proxy with HTTPS ==="
sudo tee /etc/httpd/conf.d/muttracker.conf > /dev/null <<'EOF'
<VirtualHost *:80>
    ServerName muttracker
    Redirect permanent / https://%{HTTP_HOST}/
</VirtualHost>

<VirtualHost *:443>
    ServerName muttracker
    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/muttracker.crt
    SSLCertificateKeyFile /etc/pki/tls/private/muttracker.key

    # Security headers
    Header always set Strict-Transport-Security "max-age=31536000"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "DENY"

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:5000/
    ProxyPassReverse / http://127.0.0.1:5000/
</VirtualHost>
EOF

echo "=== [7/8] Creating systemd service for Flask ==="
sudo tee /etc/systemd/system/muttracker.service > /dev/null <<'EOF'
[Unit]
Description=MUT Tracker Flask Dashboard
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/muttracker
ExecStart=/usr/bin/python3 /opt/muttracker/dashboard.py
Restart=on-failure
Environment=MUT_DB_PATH=/opt/muttracker/mut_tracker.db

[Install]
WantedBy=multi-user.target
EOF

echo "=== [8/8] Starting services ==="
sudo systemctl daemon-reload
sudo systemctl enable --now httpd
sudo systemctl enable --now muttracker

echo ""
echo "============================================================"
echo "DEPLOYMENT COMPLETE"
echo "============================================================"
echo "Visit https://$(curl -s ifconfig.me)/ in your browser"
echo "(Accept the self-signed certificate warning)"
echo ""
