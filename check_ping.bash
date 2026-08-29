#!/bin/bash

set -u

# ============================================================
# Alienware -> robo25 NUC
# Wired Link-Local connection check
# ============================================================

TARGET_HOST="robo25-NUC13ANHi5.local"
INTERFACE="enx6c6e070b4373"
PING_COUNT=3

echo "========================================"
echo " robo25 NUC wired connection check"
echo "========================================"

# ------------------------------------------------------------
# 1. Interface existence
# ------------------------------------------------------------

if [ ! -d "/sys/class/net/${INTERFACE}" ]; then
    echo "[ERROR] Interface '${INTERFACE}' does not exist."
    exit 1
fi

echo "[OK] Interface exists: ${INTERFACE}"

# ------------------------------------------------------------
# 2. Physical link
# ------------------------------------------------------------

CARRIER="$(cat "/sys/class/net/${INTERFACE}/carrier" 2>/dev/null || echo 0)"

if [ "${CARRIER}" != "1" ]; then
    echo "[ERROR] Ethernet carrier is not detected."
    exit 1
fi

echo "[OK] Ethernet carrier detected."

# ------------------------------------------------------------
# 3. Local Link-Local IPv4
# ------------------------------------------------------------

LOCAL_IP="$(
    ip -4 -o addr show dev "${INTERFACE}" \
    | awk '{print $4}' \
    | cut -d/ -f1 \
    | grep '^169\.254\.' \
    | head -n1
)"

if [ -z "${LOCAL_IP}" ]; then
    echo "[ERROR] No IPv4 Link-Local address on ${INTERFACE}."
    exit 1
fi

echo "[OK] Local Link-Local: ${LOCAL_IP}"

# ------------------------------------------------------------
# 4. Resolve hostname via Avahi D-Bus
#    IMPORTANT:
#    Resolve only through the specified Ethernet interface.
# ------------------------------------------------------------

IFINDEX="$(cat "/sys/class/net/${INTERFACE}/ifindex")"

echo "[INFO] Resolving '${TARGET_HOST}' via ${INTERFACE}..."
echo "[INFO] Interface index: ${IFINDEX}"

DBUS_RESULT="$(
    timeout 5 \
    gdbus call \
        --system \
        --dest org.freedesktop.Avahi \
        --object-path / \
        --method org.freedesktop.Avahi.Server.ResolveHostName \
        "${IFINDEX}" \
        0 \
        "${TARGET_HOST}" \
        0 \
        0 \
        2>/dev/null
)"

if [ $? -ne 0 ] || [ -z "${DBUS_RESULT}" ]; then
    echo "[ERROR] Avahi hostname resolution failed on ${INTERFACE}."
    exit 1
fi

TARGET_IP="$(
    echo "${DBUS_RESULT}" \
    | grep -oE "'([0-9]{1,3}\.){3}[0-9]{1,3}'" \
    | head -n1 \
    | tr -d "'"
)"

if [ -z "${TARGET_IP}" ]; then
    echo "[ERROR] Could not extract IPv4 address from Avahi response."
    echo "[DEBUG] ${DBUS_RESULT}"
    exit 1
fi

echo "[OK] ${TARGET_HOST} -> ${TARGET_IP}"

# ------------------------------------------------------------
# 5. Require Link-Local peer
# ------------------------------------------------------------

if [[ "${TARGET_IP}" != 169.254.* ]]; then
    echo "[ERROR] Resolved address is not Link-Local:"
    echo "        ${TARGET_IP}"
    exit 1
fi

echo "[OK] Remote address is Link-Local."

# ------------------------------------------------------------
# 6. Ping explicitly through wired interface
# ------------------------------------------------------------

echo "[INFO] Pinging ${TARGET_IP} via ${INTERFACE}..."

if ! ping \
    -I "${INTERFACE}" \
    -c "${PING_COUNT}" \
    -W 2 \
    "${TARGET_IP}"
then
    echo
    echo "[ERROR] Ping failed."
    exit 1
fi

echo
echo "========================================"
echo "[OK] Wired connection is ready."
echo "     Host      : ${TARGET_HOST}"
echo "     Interface : ${INTERFACE}"
echo "     Local IP  : ${LOCAL_IP}"
echo "     Remote IP : ${TARGET_IP}"
echo "========================================"

exit 0