#! /bin/bash

source meshtastic/bin/activate

# Delete previous logs
#rm received_messages.log
#rm combined_messages.log

# Listen for messages from a specific node for 120 minutes
python3 meshtastic_listener.py --log_file "received_messages.log" --sender_node_id "eb314389" --run_time 120

# Format received messages into single message
python3 meshtastic_input.py received_messages.log

# Decode and unzip the jpg
./decodebase64_unzip_jpeg.sh

# Upload the image
TIMESTAMP=$(date +"%Y%m%d%H%M%S")
# Update <username>, <ipaddress>, and <path> appropriately
rsync -vz -e 'ssh -i /home/pi/.ssh/id_rsa' restored.jpg <username>@<ipaddress>:<path>/$TIMESTAMP-restored.jpg

deactivate
