#!/usr/bin/env python3
"""
Combined Meshtastic Receiver & Processor (with modular connection support)

This script mimics your previous meshtastic_listener.py behavior.
It connects to Meshtastic either via TCP (default) or via Serial (if specified).
It filters incoming messages:
  - It uses the "fromId" field—if it starts with "!", that character is stripped.
  - Only messages from the desired sender (given by --sender_node_id) are processed.
  - It checks that the text field begins with the specified header (e.g. "pn")
    followed by a number and an exclamation mark.
Matching messages are logged (to received_messages.log) and stored in-memory.
The main loop prints periodic progress updates to the console.
After either the expected number of messages is received (or the run time elapses),
the script:
  • Combines the payloads (removing header prefixes)
  • Decodes and decompresses the combined Base64 data to restore an image
  • Saves the image to disk and uploads it via rsync

Usage example:
   python3 combined_receiver.py --sender_node_id eb314389 --run_time 5 --header pn --expected 5 --output restored.jpg \
       --remote_target "jonatello@192.168.2.4:/mnt/RaidZ/Master/Pictures/Motion/farmalytics3/" \
       --ssh_key /home/pi/.ssh/id_rsa --connection tcp --tcp_host localhost --tcp_port 8080 --poll_interval 10

Use --connection serial if you wish to switch from TCP.
"""

import argparse
import base64
import gzip
import logging
import re
import signal
import subprocess
import sys
import threading
import time

# We'll import the TCPInterface when using TCP; serial_interface when using serial.
# (These imports will be done conditionally in main.)
#from meshtastic.tcp_interface import TCPInterface  

# ------------------------------------------------------------------------------
# Logging configuration (similar to the old meshtastic_listener.py)
# ------------------------------------------------------------------------------
logger = logging.getLogger("CombinedReceiver")
logger.setLevel(logging.DEBUG)
logger.propagate = False  # prevent double logging

# Console handler for INFO-level messages.
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# File handler for received messages.
class ReceivedFilter(logging.Filter):
    def filter(self, record):
        return getattr(record, "received", False) is True

received_handler = logging.FileHandler("received_messages.log")
received_handler.setFormatter(console_formatter)
received_handler.setLevel(logging.INFO)
received_handler.addFilter(ReceivedFilter())
logger.addHandler(received_handler)

# File handler for debug messages.
class DebugFilter(logging.Filter):
    def filter(self, record):
        return not getattr(record, "received", False)

debug_handler = logging.FileHandler("debug_messages.log")
debug_handler.setFormatter(console_formatter)
debug_handler.setLevel(logging.DEBUG)
debug_handler.addFilter(DebugFilter())
logger.addHandler(debug_handler)

# ------------------------------------------------------------------------------
# Global state
# ------------------------------------------------------------------------------
received_messages = {}  # Maps numeric header -> message text.
state_lock = threading.Lock()
running = True        # Controls the polling loop.
args = None           # to be set in main()
iface = None          # Global Meshtastic interface instance (TCPInterface or SerialInterface).

# ------------------------------------------------------------------------------
# onReceive Callback (adapted from your previous listener)
# ------------------------------------------------------------------------------
def onReceive(packet, interface=None):
    """
    Callback invoked on each incoming message.
    
    It looks for the "fromId" field. If that field starts with "!", the "!" is stripped off.
    If the resulting sender matches the desired sender (args.sender_node_id), then we check
    the text field for the expected header pattern <header><num>!<payload>.
    If the pattern matches, store the message keyed by the numeric value.
    """
    try:
        raw_sender = packet.get("fromId")
        if not raw_sender:
            logger.debug("Received packet with no 'fromId'; ignoring.", extra={"received": False})
            return
        # Strip leading "!" if present.
        sender = raw_sender[1:] if raw_sender.startswith("!") else raw_sender

        if str(sender) != str(args.sender_node_id):
            logger.debug(f"Ignored message from sender {raw_sender} (filter: {args.sender_node_id}).", extra={"received": False})
            return

        # Try to retrieve message text from the decoded part (if available), else directly.
        text = None
        if "decoded" in packet and "text" in packet["decoded"]:
            text = packet["decoded"]["text"]
        if not text:
            text = packet.get("text")
        if not text:
            logger.debug("Packet has no text; ignoring.", extra={"received": False})
            return

        text = text.strip()
        pattern = r"^" + re.escape(args.header) + r"(\d+)!"
        m = re.match(pattern, text)
        if m:
            num = int(m.group(1))
            with state_lock:
                if num not in received_messages:
                    received_messages[num] = text
                    logger.info(f"Stored message {args.header}{num} from sender {sender}.", extra={"received": True})
        else:
            logger.debug(f"Ignored message not matching pattern: {text}", extra={"received": False})
    except Exception as e:
        logger.error(f"Exception in onReceive: {e}", extra={"received": False})

# ------------------------------------------------------------------------------
# Signal Handler
# ------------------------------------------------------------------------------
def signal_handler(sig, frame):
    logger.info("Signal received, shutting down...", extra={"received": False})
    global running, iface
    running = False
    if iface:
        iface.close()
    sys.exit(0)

# ------------------------------------------------------------------------------
# Utility Functions: compute progress, combine messages, decode/decompress, upload image
# ------------------------------------------------------------------------------
def compute_progress():
    with state_lock:
        if not received_messages:
            return 0, 0
        total_found = len(received_messages)
        max_header = max(received_messages.keys())
    return total_found, max_header

def combine_messages():
    with state_lock:
        keys = sorted(received_messages.keys())
        parts = []
        pattern = re.compile(r"^" + re.escape(args.header) + r"\d+!")
        for num in keys:
            text = received_messages[num]
            payload = pattern.sub("", text, count=1).strip()
            parts.append(payload)
    return "".join(parts)

def decode_and_save_image(combined_base64, output_file):
    try:
        decoded = base64.b64decode(combined_base64)
        decompressed = gzip.decompress(decoded)
    except Exception as e:
        logger.error(f"Error decoding/decompressing image: {e}", extra={"received": False})
        sys.exit(1)
    with open(output_file, "wb") as f:
        f.write(decompressed)
    logger.info(f"Image saved to {output_file}", extra={"received": False})

def upload_image(image_file, remote_target, ssh_key):
    timestamp = time.strftime("%Y%m%d%H%M%S")
    remote_path = f"{remote_target.rstrip('/')}/{timestamp}-restored.jpg"
    try:
        subprocess.check_call(["rsync", "-vz", "-e", f"ssh -i {ssh_key}", image_file, remote_path])
    except subprocess.CalledProcessError as e:
        logger.error(f"Error uploading image: {e}", extra={"received": False})
        sys.exit(1)
    logger.info(f"Image uploaded to {remote_path}", extra={"received": False})

# ------------------------------------------------------------------------------
# Main Execution Flow
# ------------------------------------------------------------------------------
def main():
    global args, iface, running
    parser = argparse.ArgumentParser(description="Combined Meshtastic Receiver & Processor")
    parser.add_argument("--sender_node_id", required=True, help="Sender node ID to filter messages from.")
    parser.add_argument("--run_time", type=int, required=True, help="Run time (in minutes) before the script terminates.")
    parser.add_argument("--header", type=str, default="pn", help="Header prefix expected in messages (default: pn)")
    parser.add_argument("--expected", type=int, default=5, help="Expected number of messages (default: 5)")
    parser.add_argument("--output", type=str, default="restored.jpg", help="Output image file (default: restored.jpg)")
    parser.add_argument("--remote_target", type=str, default="jonatello@192.168.2.4:/mnt/RaidZ/Master/Pictures/Motion/farmalytics3/",
                        help="Remote target for uploading the image")
    parser.add_argument("--ssh_key", type=str, default="/home/pi/.ssh/id_rsa", help="SSH identity file")
    parser.add_argument("--poll_interval", type=int, default=10, help="Seconds between progress checks (default: 10)")
    parser.add_argument("--connection", type=str, choices=["tcp", "serial"], default="tcp",
                        help="Connection type to Meshtastic device (default: tcp)")
    parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost)")
    parser.add_argument("--tcp_port", type=int, default=8080, help="TCP port (default: 8080)")  # Not used in this legacy TCPInterface
    args = parser.parse_args()

    # Set up signal handlers.
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Connecting to Meshtastic device...", extra={"received": False})
    if args.connection == "tcp":
        try:
            # Use TCPInterface (legacy import).
            from meshtastic.tcp_interface import TCPInterface
            iface = TCPInterface(hostname=args.tcp_host)
            # Subscribe to incoming messages via pubsub:
            from pubsub import pub
            pub.subscribe(onReceive, "meshtastic.receive")
            logger.info(f"Connected to Meshtastic TCP interface on {args.tcp_host}", extra={"received": False})
        except Exception as e:
            logger.error(f"Error connecting via TCP: {e}", extra={"received": False})
            sys.exit(1)
    else:  # Use serial.
        try:
            from meshtastic import serial_interface
            iface = serial_interface.SerialInterface()
            iface.onReceive = onReceive
            logger.info("Connected to Meshtastic serial interface.", extra={"received": False})
        except Exception as e:
            logger.error(f"Error connecting via Serial: {e}", extra={"received": False})
            sys.exit(1)

    logger.info(f"Listening for messages with header '{args.header}' from node '{args.sender_node_id}'", extra={"received": False})
    logger.info(f"Expected messages: {args.expected}", extra={"received": False})

    end_time = time.time() + args.run_time * 60
    while running and time.time() < end_time:
        total_found, max_header = compute_progress()
        logger.info(f"Progress: {total_found} message(s) received; highest header: {max_header}", extra={"received": False})
        if total_found >= args.expected:
            logger.info("Required messages received.", extra={"received": False})
            break
        logger.info(f"Waiting {args.poll_interval} seconds before next check...", extra={"received": False})
        time.sleep(args.poll_interval)

    running = False
    if iface:
        iface.close()
        logger.info("Meshtastic interface closed.", extra={"received": False})

    logger.info("Combining messages...", extra={"received": False})
    combined = combine_messages()
    logger.info(f"Combined payload length: {len(combined)}", extra={"received": False})

    decode_and_save_image(combined, args.output)
    upload_image(args.output, args.remote_target, args.ssh_key)

    logger.info("Pipeline complete.", extra={"received": False})

if __name__ == "__main__":
    main()
