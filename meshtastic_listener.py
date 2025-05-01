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
# =============================================================================
logger = logging.getLogger("MeshtasticListener")
logger.setLevel(logging.DEBUG)

info_handler = TimedRotatingFileHandler("received_messages.log", when='H', interval=1, backupCount=24)
debug_handler = TimedRotatingFileHandler("debug_messages.log", when='H', interval=1, backupCount=24)

formatter = logging.Formatter('%(message)s')
info_handler.setFormatter(formatter)
debug_handler.setFormatter(formatter)

logger.addHandler(info_handler)
logger.addHandler(debug_handler)
logger.propagate = False

# =============================================================================
# Function to handle incoming messages
# =============================================================================
def onReceive(packet, interface):
    raw_sender_id = packet.get("fromId")
    if raw_sender_id is None:
        raw_sender_id = "<Unknown Sender>"
        logger.debug("Received packet with no sender ID")
    else:
        raw_sender_id = raw_sender_id[1:] if raw_sender_id.startswith("!") else raw_sender_id

    decoded = packet.get("decoded", {})
    text = decoded.get("text", "<No Text>")
    portnum = decoded.get("portnum", "<Unknown Port>")
    payload_bytes = decoded.get("payload", b"<No Payload>")

    try:
        payload = payload_bytes.decode('utf-8') if isinstance(payload_bytes, bytes) else payload_bytes
    except UnicodeDecodeError:
        payload = "<Invalid UTF-8 Payload>"

    bitfield = decoded.get("bitfield", "<No Bitfield>")
    packet_id = packet.get("id", "Unknown ID")
    rx_time = packet.get("rxTime", "No rxTime")
    rx_snr = packet.get("rxSnr", "No rxSnr")
    hop_limit = packet.get("hopLimit", "No hopLimit")
    rx_rssi = packet.get("rxRssi", "No rxRssi")

    log_data = {
        "SenderID": raw_sender_id,
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

    if raw_sender_id == SENDER_NODE_ID and portnum == "TEXT_MESSAGE_APP":
        logger.info(json.dumps(log_data, indent=4))
        for h in logger.handlers:
            h.flush()
        print("Logged message:", json.dumps(log_data, indent=4))
    else:
        print(f"Message from other node or port ignored: SenderID={raw_sender_id}, Port={portnum}")

pub.subscribe(onReceive, "meshtastic.receive")

def check_connection(interface):
    try:
        interface.sendText("Connection check")
        print("Connection is healthy.")
    except Exception as e:
        print("Connection check failed:", e)
        logger.error(f"Connection check failed: {e}")

try:
    interface = TCPInterface(hostname="localhost")
    print("Connected to Meshtastic TCP interface on localhost")
except Exception as e:
    print("Failed to connect via TCP:", e)
    logger.error(f"Failed to connect via TCP: {e}")
    exit(1)

print("Listening for incoming messages... Press Ctrl+C to exit.")

parser = argparse.ArgumentParser(description="Meshtastic message listener.")
parser.add_argument("--sender_node_id", required=True, help="The ID of the sender node to filter messages from.")
parser.add_argument("--run_time", type=int, required=True, help="The time (in minutes) for the script to run before terminating.")
args = parser.parse_args()

SENDER_NODE_ID = args.sender_node_id
end_time = time.time() + args.run_time * 60

try:
    while time.time() < end_time:
        time.sleep(30)
        print("Still running...")
        check_connection(interface)
except KeyboardInterrupt:
    print("Exiting listener.")
finally:
    interface.close()
    logging.shutdown()
