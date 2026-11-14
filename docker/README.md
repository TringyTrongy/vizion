# Vizion in Docker (M3)

`Dockerfile` packages `pi/` (detector, dashboard, LEDs, MQTT link) for the Pi 5 (arm64). `docker-compose.yml` runs it next to the Mosquitto broker, both with `restart: unless-stopped`.

## Build and start

```sh
sudo apt install docker.io docker-compose-plugin
sudo systemctl enable docker            # Docker itself starts at boot
sudo usermod -aG docker $USER && newgrp docker
sudo mqtt/setup_broker.sh --files-only  # certs + passwords (git-ignored)
echo "VIZION_MQTT_PASSWORD=<the vizion password>" > docker/.env && chmod 600 docker/.env
getent group gpio                        # put this id in docker-compose.yml group_add
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml ps
```

Open `http://<pi>:8765/station`. Stop any non-Docker dashboard first: only one program can use the camera.

## Cold-boot test (the M3 task)

1. Containers running, parts on the table, LED lit.
2. Pull the Pi's power. Wait 10 s. Plug it in and start a stopwatch.
3. Nobody logs in. Docker starts at boot, `restart: unless-stopped` starts both containers, the model loads, and the LED lights.
4. Record: time to LED on, and `docker ps` showing `Up … (healthy)`.

The image also has a `HEALTHCHECK` (`/api/state` must answer), so `docker ps` shows when it is really ready.

## Devices

| Host | Container | Why |
|---|---|---|
| `/dev/video0` | same | the webcam |
| `/dev/gpiochip0` | same | LEDs (Pi 5; older kernels call it `/dev/gpiochip4`) |

The container runs as the non-root user `vizion` with all capabilities dropped and `no-new-privileges`.
