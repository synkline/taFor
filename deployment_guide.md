# Linux Deployment Guide

This guide explains how to host the TAF Generator application on a Linux server (e.g., Ubuntu 22.04).

## 1. Server Preparation

Update the system and install necessary dependencies:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv nginx -y
```

## 2. Project Setup

Clone the repository and set up a virtual environment:
```bash
git clone https://github.com/synkline/taFor.git
cd taFor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

## 3. Environment Configuration

Create a `.env` file for any environment-specific settings (optional but recommended):
```bash
touch .env
```

## 4. Running with Gunicorn

Test the application with Gunicorn:
```bash
gunicorn --bind 0.0.0.0:5000 app:app
```

## 5. Systemd Service

To keep the app running in the background and ensure it starts on boot, create a systemd service file:

`/etc/systemd/system/tafor.service`:
```ini
[Unit]
Description=Gunicorn instance to serve TAF Generator
After=network.target

[Service]
User=your_username
Group=www-data
WorkingDirectory=/path/to/taFor
Environment="PATH=/path/to/taFor/venv/bin"
ExecStart=/path/to/taFor/venv/bin/gunicorn --workers 3 --bind unix:tafor.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl start tafor
sudo systemctl enable tafor
```

## 6. Nginx Reverse Proxy

Configure Nginx to route traffic to the Gunicorn socket:

`/etc/nginx/sites-available/tafor`:
```nginx
server {
    listen 80;
    server_name your_domain_or_ip;

    location / {
        include proxy_params;
        proxy_pass http://unix:/path/to/taFor/tafor.sock;
    }
}
```

Enable the configuration and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/tafor /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
```

## 7. Portability Note
After the upcoming code refactor, the application will automatically detect its location and use a local `imd_cache` folder within the project directory, so you won't need to manually configure paths on Linux.
