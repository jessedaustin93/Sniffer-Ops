#!/usr/bin/env bash
set -euo pipefail

LOG=/var/log/ethrox-detect-usb-rescue.log

{
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ethrox-detect-usb-rescue start"

  if id jesse >/dev/null 2>&1; then
    install -d -m 0700 -o jesse -g jesse /home/jesse/.ssh
    if [ -f /home/jesse/.ssh/authorized_keys ]; then
      chown jesse:jesse /home/jesse/.ssh/authorized_keys
      chmod 0600 /home/jesse/.ssh/authorized_keys
    fi
  fi

  for _ in $(seq 1 30); do
    [ -d /sys/class/net/usb0 ] && break
    sleep 1
  done

  if [ -d /sys/class/net/usb0 ]; then
    ip link set usb0 up || true
    ip addr replace 192.168.7.2/24 dev usb0 || true
    ip -br addr show usb0 || true
  else
    echo "usb0 not present"
  fi

  systemctl restart ssh || systemctl restart sshd || true
  systemctl is-active ssh || systemctl is-active sshd || true
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ethrox-detect-usb-rescue done"
} >> "$LOG" 2>&1
