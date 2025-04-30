#! /bin/bash

source meshtastic/bin/activate

# Listen for messages from a specific node for 5 minutes
python3 meshtastic_listener.py --sender_node_id "6209a0bd" --run_time 60

# Format received messages into single message
python3 meshtastic_input.py received_messages.log

# Decode and unzip the jpg
./decodebase64_unzip_jpeg.sh

deactivate
