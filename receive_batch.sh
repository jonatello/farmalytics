#!/bin/bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  -v <venv_activate>   Virtual environment activation script (default: meshtastic/bin/activate)
  -L <log>             Received messages log file (default: received_messages.log)
  -n <node_id>         Sender node ID to filter (default: eb314389)
  -t <run_time>        Listening runtime in seconds (default: 300)
  -H <header>          Header filter for formatting messages (default: pb)
  -I <combined_log>    Output file path from meshtastic_input.py (default: combined_message.log)
  -d <decode_script>   Path to the decode script (default: ./decodebase64_unzip_jpeg.sh)
  -u <remote_target>   Remote upload target in the form user@host:remote_dir 
                       (default: jonatello@192.168.2.4:/mnt/RaidZ/Master/Pictures/)
  -k <ssh_key>         SSH identity file (default: /home/pi/.ssh/id_rsa)
  -h                   Show this help message
EOF
  exit 1
}

# Default parameter values
venv_activate="meshtastic/bin/activate"
received_log="received_messages.log"
node_id="ab12345"
run_time=300         # Listening runtime in seconds, default 300 (5 minutes)
header="ab"
combined_log="combined_message.log"
decode_script="./decodebase64_unzip_jpeg.sh"
remote_target="user@hostname:/path/"
ssh_key="/home/pi/.ssh/id_rsa"

# Parse options
while getopts "v:L:n:t:H:I:d:u:k:h" opt; do
  case "$opt" in
    v) venv_activate="$OPTARG" ;;
    L) received_log="$OPTARG" ;;
    n) node_id="$OPTARG" ;;
    t) run_time="$OPTARG" ;;
    H) header="$OPTARG" ;;
    I) combined_log="$OPTARG" ;;
    d) decode_script="$OPTARG" ;;
    u) remote_target="$OPTARG" ;;
    k) ssh_key="$OPTARG" ;;
    h) usage ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

# Helper function to check command exit status.
check_success() {
  if [ $? -ne 0 ]; then
    echo "Error: $1 failed." >&2
    exit 1
  fi
}

echo "=== Activating virtual environment: $venv_activate ==="
source "$venv_activate"

echo "=== Deleting previous log files ==="
rm -f *.log

echo "=== Listening for messages ==="
echo "Listening for ${run_time} seconds from node ID $node_id; log file: $received_log"
# Invoke meshtastic_listener.py using "--run_time" as required.
python3 meshtastic_listener.py --received_log "$received_log" --sender_node_id "$node_id" --run_time "$run_time"
check_success "Meshtastic listener"

echo "=== Formatting received messages ==="
python3 meshtastic_input.py "$received_log" --header "$header"
check_success "Meshtastic input formatting"
# This produces the combined output file (default: combined_message.log)

echo "=== Decoding and unzipping image ==="
$decode_script -i "$combined_log"
check_success "Decoding and unzipping"

echo "=== Uploading restored image ==="
TIMESTAMP=$(date +"%Y%m%d%H%M%S")
# Remove any trailing slash from remote_target and append a timestamped filename.
remote_upload="${remote_target%/}/$TIMESTAMP-restored.jpg"
rsync -vz -e "ssh -i $ssh_key" restored.jpg "$remote_upload"
check_success "Image upload"

echo "=== Deactivating virtual environment ==="
deactivate

echo "=== Pipeline complete ==="
echo "Restored image saved to 'restored.jpg' and uploaded as '$remote_upload'"
