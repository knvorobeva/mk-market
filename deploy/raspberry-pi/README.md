# Raspberry Pi deployment

This setup runs the backend 24/7 on Raspberry Pi with Docker and `systemd`.

## 1) Copy project to Raspberry Pi

```bash
sudo mkdir -p /opt/trade-agent
sudo chown -R $USER:$USER /opt/trade-agent
git clone <YOUR_REPO_URL> /opt/trade-agent
cd /opt/trade-agent/deploy/raspberry-pi
```

## 2) Create environment file

```bash
cp .env.example .env
nano .env
```

Set at least:
- `APP_SECRET`
- `GROQ_API_KEY`
- `TINKOFF_API_TOKEN`
- `TINKOFF_ACCOUNT_ID`
- `AUTH_DISABLED` (set to `1` to disable login/registration)
- `TINKOFF_API_TARGET` (`prod` or `sandbox`)

## 3) Start with Docker Compose

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f trade-agent
```

Service will be available on `http://<RPI_IP>:8000`.

## 4) Enable autostart with systemd

```bash
sudo cp trade-agent.service /etc/systemd/system/trade-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now trade-agent
sudo systemctl status trade-agent
```

## 5) Common operations

```bash
cd /opt/trade-agent/deploy/raspberry-pi
docker compose pull
docker compose up -d --build
docker compose logs -f trade-agent
sudo systemctl restart trade-agent
```

## Notes

- Persistent app data is stored in `backend/data`.
- Do not commit `.env` to git.
- Current backend contains no direct T-Invest API calls yet; token is prepared for next integration step.
