#!/bin/sh
# Sets up the secure Vizion MQTT broker on the Pi (native Mosquitto), or only the certificates and
# password file with --files-only (for docker/docker-compose.yml).
#
#   sudo ./setup_broker.sh               # install mosquitto, make certs + users, start on 8883
#   ./setup_broker.sh --files-only       # only mqtt/certs/ and mqtt/passwd (git-ignored)
#
# It asks for the two passwords (vizion, viewer); nothing secret is written into the repo.
set -eu
cd "$(dirname "$0")"
HOST="${VIZION_MQTT_CN:-$(hostname)}"
mkdir -p certs

if [ ! -f certs/ca.key ]; then
    echo "Making a private certificate authority and a server certificate for $HOST"
    openssl req -x509 -new -nodes -newkey rsa:2048 -days 825 -subj "/CN=Vizion MQTT CA" \
        -keyout certs/ca.key -out certs/ca.crt
    openssl req -new -nodes -newkey rsa:2048 -subj "/CN=$HOST" -keyout certs/server.key -out certs/server.csr
    printf 'subjectAltName=DNS:%s,DNS:localhost,DNS:mosquitto,IP:127.0.0.1\n' "$HOST" > certs/san.ext
    openssl x509 -req -in certs/server.csr -CA certs/ca.crt -CAkey certs/ca.key -CAcreateserial \
        -days 825 -extfile certs/san.ext -out certs/server.crt
    chmod 600 certs/ca.key certs/server.key
fi

if [ ! -f passwd ]; then
    : > passwd
    for user in vizion viewer; do
        echo "Password for MQTT user '$user':"
        mosquitto_passwd passwd "$user"
    done
    chmod 600 passwd
fi

[ "${1:-}" = "--files-only" ] && { echo "Wrote mqtt/certs/ and mqtt/passwd"; exit 0; }

apt-get install -y mosquitto mosquitto-clients
install -m 644 mosquitto.conf /etc/mosquitto/conf.d/vizion.conf
install -m 640 -o root -g mosquitto passwd /etc/mosquitto/passwd
install -m 644 acl /etc/mosquitto/acl
install -d -m 755 /etc/mosquitto/certs
install -m 644 certs/ca.crt certs/server.crt /etc/mosquitto/certs/
install -m 640 -o root -g mosquitto certs/server.key /etc/mosquitto/certs/
# the stock config opens a plain listener on 1883 for localhost only; Vizion uses 8883
systemctl enable --now mosquitto
systemctl restart mosquitto
echo "Broker running on 8883 (TLS + password). Test it: ./test_security.sh"
