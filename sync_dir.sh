#!/bin/bash

set -euo pipefail

# lock it
PIDFILE="/tmp/$(basename "${BASH_SOURCE[0]%.*}.pid")"
exec 200>${PIDFILE}
/bin/flock -n 200 || ( echo "${BASH_SOURCE[0]} script is already running. Aborting . ." && exit 1 )
PID=$$
echo ${PID} 1>&200
trap "rm -f $PIDFILE; exit" 0 2 3 15

MOUNT_POINT=$1
LOCAL_DIR=$2
SSH_KEY=$3



rsync  --remove-source-files -rtvk --exclude='@eaDir/*' --exclude=".*"  --progress --human-readable  -avh  -e "ssh  -x -T -c aes128-gcm@openssh.com -o Compression=no -i $SSH_KEY -p22"  "$MOUNT_POINT" "$LOCAL_DIR"




