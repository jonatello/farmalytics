#!/usr/bin/env python3
"""
Usage:
    python3 meshtastic_listener.py --sender_node_id SENDER_NODE_ID --run_time RUN_TIME --log_file LOG_FILE

Arguments:
    --sender_node_id: The ID of the sender node to filter messages from.
    --run_time: The time (in minutes) for the script to run before terminating.
    --log_file: Path to the log file for outputting received messages.

Examples:
    python3 meshtastic_listener.py --sender_node_id "6209a0bd" --run_time 5 --log_file "custom_log.log"
"""

import logging
import json
import time
import argparse
import sys
from meshtastic.tcp_interface import TCPInterface
from pubsub import pub

# ---------------------- Command-Line Argument Parsing ----------------------

parser = argparse.ArgumentParser(description="Meshtastic message listener.")
parser.add_argument("--sender_node_id", required=True, help="The ID of the sender node to filter messages from.")
parser.add_argument("--run_time", type=int, required=True, help="The time (in minutes) for the script to run before terminating.")
parser.add_argument("--log_file", required=True, help="Path to the log file for outputting received messages.")
args = parser.parse_args()

# Assign parsed arguments to module-level (global) variables.
SENDER_NODE_ID = args.sender_node_id
RUN_TIME_MINUTES = args.run_time
LOG_FILE = args.log_file

# ---------------------- Logging Configuration ----------------------

logger = logging.getLogger("MeshtasticListener")
logger.setLevel(logging.DEBUG)
logger.propagate = False

# Console handler for immediate feedback.
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# File handler for detailed logging.
file_handler = logging.FileHandler(LOG_FILE)
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
file_handler.setLevel(logging.DEBUG)
logger.addHandler(file_handler)

# ---------------------- Callback Function for Receiving Messages ----------------------

def onReceive(packet, interface):
    """
    Callback function to handle incoming meshtastic messages.
    Filters messages by the expected sender (SENDER_NODE_ID) and port, and logs details.
    
    Parameters:
        packet (dict): The incoming message packet.
        interface: The meshtastic interface.
    
    Uses:
        SENDER_NODE_ID (global): The expected sender node ID.
    """
    # Process the sender ID.
    raw_sender_id = packet.get("fromId")
    if raw_sender_id is None:
        raw_sender_id = "<Unknown Sender>"
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
    rx_snr = decoded.get("rxSnr", "No rxSnr")
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

    # Filter messages by the expected sender node ID and port.
    if raw_sender_id == SENDER_NODE_ID and portnum == "TEXT_MESSAGE_APP":
        message_json = json.dumps(log_data, indent=4)
        logger.info(message_json)
        # Explicitly flush handlers to ensure log persistence.
        for handler in logger.handlers:
            handler.flush()
        print("Logged message:", message_json)
    else:
        # For messages that do not match, log the fact at DEBUG level.
        logger.debug(f"Ignored message: SenderID={raw_sender_id}, Port={portnum}")
        print(f"Message skipped: SenderID={raw_sender_id}, Port={portnum}")

# Subscribe the onReceive callback. Note: We now subscribe directly without a partial,
# ensuring the callback signature exactly matches what Meshtastic sends.
pub.subscribe(onReceive, "meshtastic.receive")

# ---------------------- Connection Health Check ----------------------

def check_connection(interface):
    """
    Checks the health of the connection by sending a test message.
    
    Parameters:
        interface: The meshtastic interface.
    
    Returns:
        bool: True if healthy; False otherwise.
    """
    try:
        interface.sendText("Connection check")
        logger.info("Connection is healthy.")
        return True
    except Exception as e:
        logger.error(f"Connection check failed: {e}")
        return False

# ---------------------- Main Execution Flow ----------------------

def main():
    # Establish connection to the Meshtastic TCP interface.
    try:
        interface = TCPInterface(hostname="localhost")
        logger.info("Connected to Meshtastic TCP interface on localhost")
    except Exception as e:
        logger.error(f"Failed to connect via TCP: {e}")
        sys.exit(1)
    
    logger.info("Listening for incoming messages... Press Ctrl+C to exit.")
    end_time = time.time() + RUN_TIME_MINUTES * 60  # Compute the stop time.

    try:
        while time.time() < end_time:
            time.sleep(30)
            logger.info("Still running...")
            if not check_connection(interface):
                logger.warning("Connection appears unhealthy. Continuing to listen...")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting listener.")
    finally:
        interface.close()
        logger.info("Interface closed. Shutting down logger.")
        logging.shutdown()

if __name__ == "__main__":
    main()
