#!/usr/bin/env python3
"""
Usage:
    python3 meshtastic_listener.py --sender_node_id SENDER_NODE_ID --run_time RUN_TIME

Arguments:
    --sender_node_id: The ID of the sender node to filter messages from.
    --run_time: The time (in minutes) for the script to run before terminating.

Examples:
    python3 meshtastic_listener.py --sender_node_id "6209a0bd" --run_time 5
"""

import logging
from logging.handlers import TimedRotatingFileHandler
import json
from meshtastic.tcp_interface import TCPInterface
from pubsub import pub
import time
import argparse

# =============================================================================
# Configure logging with timed rotation
#
# The log files will rotate every hour, and up to 24 backup files will be
# retained (approximately 24 hours of logs). The JSON-formatted log messages
# are written to "received_messages.log" in the working directory.
# =============================================================================
logger = logging.getLogger("MeshtasticListener")
logger.setLevel(logging.DEBUG)  # Enables capturing detailed logs (use INFO for less verbosity)

# Create a log file handler for received messages
info_handler = TimedRotatingFileHandler("received_messages.log", when='H', interval=1, backupCount=24)
# Create a log file handler for debug-level messages
debug_handler = TimedRotatingFileHandler("debug_messages.log", when='H', interval=1, backupCount=24)

# Define the log format
formatter = logging.Formatter('%(message)s')  # Simplified formatting to log pure JSON
info_handler.setFormatter(formatter)
debug_handler.setFormatter(formatter)

# Attach handlers to the logger
logger.addHandler(info_handler)
logger.addHandler(debug_handler)
logger.propagate = False  # Prevent duplicate messages being logged by the root logger

# =============================================================================
# Function to handle incoming messages
# =============================================================================
def onReceive(packet, interface):
    """
    Callback triggered when a packet is received.
    Logs detailed information about the message, including metadata and decoded content,
    in JSON format. Ignores messages not sent by the expected sender node or if the port is not TEXT_MESSAGE_APP.
    """
    # Safely retrieve the sender ID, defaulting to "<Unknown Sender>" if missing
    raw_sender_id = packet.get("fromId")
    if raw_sender_id is None:
        raw_sender_id = "<Unknown Sender>"
    # Remove prefix (e.g., "!" or others) from sender ID
    sender_id = raw_sender_id[1:] if raw_sender_id.startswith("!") else raw_sender_id

    # Extract data from the packet's decoded section
    decoded = packet.get("decoded", {})
    text = decoded.get("text", "<No Text>")  # Text content of the message (default if missing)
    portnum = decoded.get("portnum", "<Unknown Port>")  # Port number indicating message type
    payload_bytes = decoded.get("payload", b"<No Payload>")  # Raw payload data (as bytes)

    # Decode the payload into a standard string, handling potential decoding errors
    try:
        payload = payload_bytes.decode('utf-8') if isinstance(payload_bytes, bytes) else payload_bytes
    except UnicodeDecodeError:
        payload = "<Invalid UTF-8 Payload>"

    # Additional metadata extracted from the packet
    bitfield = decoded.get("bitfield", "<No Bitfield>")
    packet_id = packet.get("id", "Unknown ID")
    rx_time = packet.get("rxTime", "No rxTime")  # Timestamp of packet reception
    rx_snr = packet.get("rxSnr", "No rxSnr")  # Signal-to-noise ratio
    hop_limit = packet.get("hopLimit", "No hopLimit")  # Hop limit for packet relay
    rx_rssi = packet.get("rxRssi", "No rxRssi")  # Received signal strength indicator

    # Create a structured JSON object for logging
    log_data = {
        "SenderID": sender_id,
        "Text": text,
        "Port": portnum,
        "Payload": payload,
        "Bitfield": bitfield,
        "PacketID": packet_id,
        "RXTime": rx_time,
        "RXSnR": rx_snr,
        "HopLimit": hop_limit,
        "RXRSSI": rx_rssi
    }

    # Log and print if the sender matches the expected node ID and port is TEXT_MESSAGE_APP
    if sender_id == SENDER_NODE_ID and portnum == "TEXT_MESSAGE_APP":
        # Log the message in JSON format
        logger.info(json.dumps(log_data, indent=4))
        for h in logger.handlers:
            h.flush()  # Force log flush to ensure the message is written immediately
        print("Logged message:", json.dumps(log_data, indent=4))  # Print for console monitoring
    else:
        # Only print ignored messages to the console
        print(f"Message from other node or port ignored: SenderID={sender_id}, Port={portnum}")

# =============================================================================
# Subscribe to incoming messages published on the "meshtastic.receive" topic
# =============================================================================
pub.subscribe(onReceive, "meshtastic.receive")  # Automatically calls onReceive for each received message

# =============================================================================
# Establish connection to the Meshtastic device using TCP on localhost.
# Ensure that the Meshtastic service/daemon is running and configured for TCP connections.
# =============================================================================
try:
    interface = TCPInterface(hostname="localhost")  # Connect to Meshtastic via TCP
    print("Connected to Meshtastic TCP interface on localhost")
except Exception as e:
    print("Failed to connect via TCP:", e)
    exit(1)

# =============================================================================
# Main loop to keep the script running, listening for incoming messages.
# =============================================================================
print("Listening for incoming messages... Press Ctrl+C to exit.")

# Set up argument parser
parser = argparse.ArgumentParser(description="Meshtastic message listener.")
parser.add_argument("--sender_node_id", required=True, help="The ID of the sender node to filter messages from.")
parser.add_argument("--run_time", type=int, required=True, help="The time (in minutes) for the script to run before terminating.")
args = parser.parse_args()

# Set the expected sender node ID for filtering incoming messages
SENDER_NODE_ID = args.sender_node_id
# Calculate the end time based on the run time parameter
end_time = time.time() + args.run_time * 60
try:
    while time.time() < end_time:
        # Sleep for 30 seconds and print a heartbeat to confirm script activity
        time.sleep(30)
        print("Still running...")
except KeyboardInterrupt:
    # Gracefully handle script termination (Ctrl+C)
    print("Exiting listener.")
finally:
    # Close the interface and shut down logging
    interface.close()
    logging.shutdown()
