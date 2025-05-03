#!/bin/bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  -v <venv_activate>   Path to virtualenv activate script (default: meshtastic/bin/activate)
  -e <opt_script>      Command/script for image optimization (default: ./optimize_compress_zip_base64encode_jpg.sh)
  -q <quality>         JPEG quality factor for optimization (default: 75)
  -R <resize>          Resize dimensions (e.g., 800x600; default: 800x600)
  -O <output>          Output file from optimization (default: base64_image.gz)

  -P <send_script>     Command for sending messages (default: python3 meshtastic_send.py)
  -C <connection>      Connection type for sending (default: tcp)
  -D <destination>     Destination for Meshtastic send (default: '!47a78d36')
  -c <chunk_size>      Chunk size for sending (default: 180)
  -H <header>          Header to filter/sort messages (default: pb)
  -N                   Do NOT use ACK (by default, ACK mode is enabled)
  -S <sleep_delay>     Sleep delay between sending chunks in sync mode (default: 1)
  -m <mode>            Mode: "sync" or "async" (default: sync)
  -T <tasks>           Max concurrent tasks (used in async mode; default: 4)
  -h                   Show this help message
EOF
  exit 1
}

# Default parameter values:
VENV_ACTIVATE="meshtastic/bin/activate"
OPT_SCRIPT="./optimize_compress_zip_base64encode_jpg.sh"
QUALITY=75
RESIZE="800x600"
OPT_OUTPUT="base64_image.gz"

SEND_SCRIPT="python3 meshtastic_send.py"
CONNECTION="tcp"
DEST="!47a78d36"
CHUNK_SIZE=180
HEADER="pb"
ack_flag="--ack"   # Default is to use ACK. Use -N to disable.
SLEEP_DELAY=1
MODE="sync"        # "sync" or "async"
MAX_CONCURRENT_TASKS=4

# Parse options:
while getopts "v:e:q:R:O:P:C:D:c:H:NS:m:T:h" opt; do
  case "$opt" in
    v) VENV_ACTIVATE="$OPTARG" ;;
    e) OPT_SCRIPT="$OPTARG" ;;
    q) QUALITY="$OPTARG" ;;
    R) RESIZE="$OPTARG" ;;
    O) OPT_OUTPUT="$OPTARG" ;;
    P) SEND_SCRIPT="$OPTARG" ;;
    C) CONNECTION="$OPTARG" ;;
    D) DEST="$OPTARG" ;;
    c) CHUNK_SIZE="$OPTARG" ;;
    H) HEADER="$OPTARG" ;;
    N) ack_flag="" ;;  # Disable ACK if -N is present
    S) SLEEP_DELAY="$OPTARG" ;;
    m) MODE="$OPTARG" ;;
    T) MAX_CONCURRENT_TASKS="$OPTARG" ;;
    h) usage ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

echo "=== Activating virtual environment: $VENV_ACTIVATE ==="
source "$VENV_ACTIVATE"
# Ensure the virtual environment is activated before proceeding.

echo "=== Running Image Optimization Script ==="
echo "Command: $OPT_SCRIPT -q $QUALITY -r $RESIZE -o $OPT_OUTPUT"
$OPT_SCRIPT -q "$QUALITY" -r "$RESIZE" -o "$OPT_OUTPUT"

echo "=== Running Meshtastic Send Script ==="
if [ "$MODE" = "sync" ]; then
  echo "Sync mode with ACK flag: ${ack_flag:-(no ACK)} and sleep delay: $SLEEP_DELAY"
  $SEND_SCRIPT "$OPT_OUTPUT" --connection "$CONNECTION" --dest "$DEST" --chunk_size "$CHUNK_SIZE" --header "$HEADER" $ack_flag --sleep_delay "$SLEEP_DELAY"
elif [ "$MODE" = "async" ]; then
  echo "Async mode with max concurrent tasks: $MAX_CONCURRENT_TASKS"
  $SEND_SCRIPT "$OPT_OUTPUT" --connection "$CONNECTION" --dest "$DEST" --chunk_size "$CHUNK_SIZE" --header "$HEADER" --asynchronous --max_concurrent_tasks "$MAX_CONCURRENT_TASKS"
else
  echo "Invalid mode specified: $MODE" >&2
  exit 1
fi

echo "=== Deactivating Virtual Environment ==="
deactivate

echo "Pipeline complete."
