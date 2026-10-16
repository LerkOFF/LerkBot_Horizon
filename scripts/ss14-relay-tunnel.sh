#!/usr/bin/env bash
set -euo pipefail

# Bind only to the bot's Docker bridge. The bridge address is discovered at
# startup because Docker may assign a different subnet after recreation.
gateway=$(/usr/bin/docker network inspect starhorizon_bot_default --format '{{(index .IPAM.Config 0).Gateway}}')
if [[ -z "$gateway" ]]; then
    echo 'Docker gateway for starhorizon_bot_default is unavailable' >&2
    exit 1
fi

exec /usr/bin/ssh -N -T \
    -i /root/.ssh/id_ed25519 \
    -o BatchMode=yes \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=yes \
    -o ConnectTimeout=10 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -L "${gateway}:15433:146.0.78.52:5433" \
    -L "${gateway}:11212:146.0.78.52:1212" \
    root@82.26.150.155
