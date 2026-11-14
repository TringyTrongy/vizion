# Vizion detector + dashboard in a container, for the Raspberry Pi 5 (linux/arm64).
#
#   docker compose -f docker/docker-compose.yml up -d --build
#
# The container runs pi/dashboard.py headless on port 8765; the Pi's own Chromium kiosk (or any
# browser on the network) opens http://<pi>:8765/station. Camera and GPIO come in as devices,
# see docker-compose.yml. Cold boot: Docker starts at boot and `restart: unless-stopped` brings the
# container back, so after a power cycle the LEDs fire without anyone logging in.
FROM python:3.11.10-slim-bookworm

# OpenCV needs libgl/glib at runtime even headless; swig + gcc build lgpio when no wheel exists.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 swig gcc libc6-dev curl \
 && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch first: the default ARM wheels pull GBs of CUDA libraries the Pi cannot use.
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu
COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Non-root user in the group that owns the camera (video); gpio is added at run time (group_add).
RUN useradd --create-home --uid 1000 --groups video vizion
WORKDIR /app
COPY --chown=vizion:vizion pi/ /app/
RUN mkdir -p /app/logs && chown vizion:vizion /app/logs
USER vizion
ENV YOLO_CONFIG_DIR=/tmp/ultralytics PYTHONUNBUFFERED=1

EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=3 \
  CMD curl -fs http://127.0.0.1:8765/api/state > /dev/null || exit 1
CMD ["python", "dashboard.py", "--host", "0.0.0.0", "--port", "8765"]
