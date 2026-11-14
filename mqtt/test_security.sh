#!/bin/sh
# Proves the broker is secure: four connection attempts, the expected result of each, and PASS/FAIL.
#
#   VIZION_MQTT_PASSWORD=... ./test_security.sh [host] [cafile]
#
# 1. no username/password over TLS          -> must be REFUSED (not authorised)
# 2. wrong password over TLS                -> must be REFUSED
# 3. right password, but no TLS (plain 1883) -> must FAIL to connect (no plain listener on 8883)
# 4. right password + TLS                   -> must WORK (publishes and reads back a message)
set -u
HOST="${1:-localhost}"
CA="${2:-$(dirname "$0")/certs/ca.crt}"
PW="${VIZION_MQTT_PASSWORD:?set VIZION_MQTT_PASSWORD}"
T=vizion/selftest
fail=0

check() {  # name, expected (refused|works), command...
    name=$1; want=$2; shift 2
    out=$("$@" 2>&1); rc=$?
    if [ "$want" = refused ]; then [ $rc -ne 0 ] && r=PASS || { r=FAIL; fail=1; }
    else [ $rc -eq 0 ] && r=PASS || { r=FAIL; fail=1; }; fi
    printf '%-38s expected %-7s exit %-3s %s  | %s\n' "$name" "$want" "$rc" "$r" "$(echo "$out" | head -1)"
}

echo "Broker $HOST:8883  CA $CA  $(date '+%F %T')"
check "1 no password, TLS" refused mosquitto_pub -h "$HOST" -p 8883 --cafile "$CA" -t $T -m x
check "2 wrong password, TLS" refused mosquitto_pub -h "$HOST" -p 8883 --cafile "$CA" -u vizion -P wrong-password -t $T -m x
check "3 right password, no TLS" refused mosquitto_pub -h "$HOST" -p 8883 -u vizion -P "$PW" -t $T -m x
msg="hello-$(date +%s)"
( sleep 1; mosquitto_pub -h "$HOST" -p 8883 --cafile "$CA" -u vizion -P "$PW" -t $T -m "$msg" -q 1 ) &
check "4 right password + TLS (pub+sub)" works mosquitto_sub -h "$HOST" -p 8883 --cafile "$CA" -u vizion -P "$PW" -t $T -C 1 -W 5
wait
[ $fail -eq 0 ] && echo "ALL 4 CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit $fail
