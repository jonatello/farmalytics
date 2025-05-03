#!/usr/bin/env python3
"""
Usage:
    python3 meshtastic_listener.py --sender_node_id SENDER_NODE_ID --run_time RUN_TIME [--received_log RECEIVED_LOG] [--debug_log DEBUG_LOG]

Arguments:
    --sender_node_id: The ID of the sender node to filter messages from.
    --run_time: The time (in minutes) for the script to run before terminating.

Optional Arguments:
    --received_log: File path for outputting filtered messages (default: received_messages.log)
    --debug_log: File path for outputting all other logs (default: debug_messages.log)

Note:
    Only messages from the specified SENDER_NODE_ID and with port "TEXT_MESSAGE_APP" (the JSON INFO messages)
    will be written to the received_messages.log file. All other logs (connection events, ignored messages, etc.)
    will be written to the debug log.
    
Examples:
    python3 meshtastic_listener.py --sender_node_id "6209a0bd" --run_time 5
    python3 meshtastic_listener.py --sender_node_id "6209a0bd" --run_time 5 --received_log "my_received.log" --debug_log "my_debug.log"
"""

import logging
import json
import time
import argparse
import sys
from meshtastic.tcp_interface import TCPInterface
from pubsub import pub

# ---------------------- Custom Log Filters ----------------------

class ReceivedFilter(logging.Filter):
    """Allow only log records with extra 'received' attribute set to True."""
    def filter(self, record):
        return getattr(record, "received", False) is True

class DebugFilter(logging.Filter):
    """Allow only log records that do not have extra 'received' True."""
    def filter(self, record):
        return not getattr(record, "received", False)

# ---------------------- Command-Line Argument Parsing ----------------------

parser = argparse.ArgumentParser(description="Meshtastic message listener with separated logs.")
parser.add_argument("--sender_node_id", required=True, help="The ID of the sender node to filter messages from.")
parser.add_argument("--run_time", type=int, required=True, help="The time (in minutes) for the script to run before terminating.")
parser.add_argument("--received_log", default="received_messages.log", help="File path for filtered messages (default: received_messages.log)")
parser.add_argument("--debug_log", default="debug_messages.log", help="File path for all other logs (default: debug_messages.log)")
args = parser.parse_args()

# Module-level globals from arguments.
SENDER_NODE_ID = args.sender_node_id
RUN_TIME_MINUTES = args.run_time

# ---------------------- Logging Configuration ----------------------

logger = logging.getLogger("MeshtasticListener")
logger.setLevel(logging.DEBUG)
logger.propagate = False  # Prevent double logging via root logger

# Console handler: show all messages.
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# File handler for filtered (received) messages.
received_handler = logging.FileHandler(args.received_log)
received_handler.setFormatter(console_formatter)
received_handler.setLevel(logging.INFO)  # Filtered messages logged as INFO
received_handler.addFilter(ReceivedFilter())
logger.addHandler(received_handler)

# File handler for all other (debug) messages.
debug_handler = logging.FileHandler(args.debug_log)
debug_handler.setFormatter(console_formatter)
debug_handler.setLevel(logging.DEBUG)
debug_handler.addFilter(DebugFilter())
logger.addHandler(debug_handler)

# ---------------------- Callback Function for Receiving Messages ----------------------

def onReceive(packet, interface):
    """
    Callback to handle incoming Meshtastic messages.
    Logs a JSON dump of message info only if it matches the filtered sender and port.
    
    Parameters:
        packet (dict): The incoming message packet.
        interface: The Meshtastic interface.
    
    Uses global SENDER_NODE_ID.
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

    # Log only filtered messages from the specified sender with "TEXT_MESSAGE_APP" on the received log.
    if raw_sender_id == SENDER_NODE_ID and portnum == "TEXT_MESSAGE_APP":
        message_json = json.dumps(log_data, indent=4)
        logger.info(message_json, extra={"received": True})
        # Flush handlers if desired.
        for handler in logger.handlers:
            handler.flush()
        # Removed duplicated print() so that the filtered message is logged only once.
    else:
        logger.debug(f"Ignored message: SenderID={raw_sender_id}, Port={portnum}", extra={"received": False})
        print(f"Message skipped: SenderID={raw_sender_id}, Port={portnum}")

# Subscribe the onReceive callback (with expected signature).
pub.subscribe(onReceive, "meshtastic.receive")

# ---------------------- Connection Health Check ----------------------

def check_connection(interface):
    """
    Checks the health of the connection by sending a test message.
    
    Parameters:
        interface: The Meshtastic interface.
    
    Returns:
        bool: True if the connection is healthy; False otherwise.
    """
    try:
        interface.sendText("Connection check")
        logger.info("Connection is healthy.", extra={"received": False})
        return True
    except Exception as e:
        logger.error(f"Connection check failed: {e}", extra={"received": False})
        return False

# ---------------------- Main Execution Flow ----------------------

def main():
    try:
        interface = TCPInterface(hostname="localhost")
        logger.info("Connected to Meshtastic TCP interface on localhost", extra={"received": False})
    except Exception as e:
        logger.error(f"Failed to connect via TCP: {e}", extra={"received": False})
        sys.exit(1)
    
    logger.info("Listening for incoming messages... Press Ctrl+C to exit.", extra={"received": False})
    end_time = time.time() + RUN_TIME_MINUTES * 60

    try:
        while time.time() < end_time:
            time.sleep(30)
            logger.info("Still running...", extra={"received": False})
            if not check_connection(interface):
                logger.warning("Connection appears unhealthy. Continuing to listen...", extra={"received": False})
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting listener.", extra={"received": False})
    finally:
        interface.close()
        logger.info("Interface closed. Shutting down logger.", extra={"received": False})
        logging.shutdown()

if __name__ == "__main__":
    main()
