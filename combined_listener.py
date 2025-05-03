#!/usr/bin/env python3
"""
Optimized Meshtastic Receiver & Processor with Real-Time Tracking, Dynamic Message Handling, and Clear Summaries.
Supports TCP and Serial connections.
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

# ---------------------- Logging Configuration ----------------------
logger = logging.getLogger("MeshtasticReceiver")
logger.setLevel(logging.DEBUG)
logger.propagate = False

# Console logging (user-facing output)
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# File logging for received messages
received_handler = logging.FileHandler("received_messages.log")
received_handler.setFormatter(console_formatter)
received_handler.setLevel(logging.INFO)
logger.addHandler(received_handler)

# Debug logging (extra details for troubleshooting)
debug_handler = logging.FileHandler("debug_messages.log")
debug_handler.setFormatter(console_formatter)
debug_handler.setLevel(logging.DEBUG)
logger.addHandler(debug_handler)

# ---------------------- Global State ----------------------
received_messages = {}  # Stores valid messages in-memory, filtered by sender_node_id
combined_messages = []  # Stores sorted messages after header filtering
state_lock = threading.Lock()
running = True
args = None
iface = None
last_message_time = time.time()  # Track last received message time
highest_header = 0  # Track the highest numeric header seen
start_time = time.time()  # Track execution time

# ---------------------- Message Handling ----------------------
def onReceive(packet, interface=None):
    """Filters incoming messages, logs valid ones, and updates expected messages dynamically."""
    global last_message_time, highest_header

    try:
        raw_sender = packet.get("fromId")
        sender = raw_sender.lstrip("!") if raw_sender else None

        if sender != args.sender_node_id:
            logger.debug(f"Ignored message from sender {raw_sender} (filter: {args.sender_node_id}).")
            return

        text = packet.get("decoded", {}).get("text", "").strip() or packet.get("text", "").strip()
        if not text:
            logger.debug("Ignored packet with no text.")
            return

        # Extract header number and payload
        pattern = fr"^{re.escape(args.header)}(\d+)!"
        match = re.match(pattern, text)

        if match:
            header_num = int(match.group(1))

            with state_lock:
                received_messages[header_num] = text
                logger.info(f"Stored message {args.header}{header_num} from sender {sender}.")

                # Update expected count dynamically if new highest header is found
                if header_num > highest_header:
                    highest_header = header_num
                    logger.info(f"Updated expected message count to {highest_header}.")

                # Log additional details in debug mode
                if args.debug:
                    logger.debug(f"Received message details: Sender={sender}, Header={header_num}, RawText={text}")

                # Write valid messages to received_messages.log
                with open("received_messages.log", "a") as log_file:
                    log_file.write(f"{text}\n")

                # Update timestamp for inactivity tracking
                last_message_time = time.time()
        else:
            logger.debug(f"Ignored message not matching pattern: {text}")
    except Exception as e:
        logger.error(f"Exception in onReceive: {e}")

# ---------------------- Connection Handling ----------------------
def connect_meshtastic():
    """Establishes a Meshtastic connection via TCP or Serial."""
    global iface
    logger.info("Connecting to Meshtastic device...")
    try:
        if args.connection == "tcp":
            from meshtastic.tcp_interface import TCPInterface
            iface = TCPInterface(hostname=args.tcp_host)
            from pubsub import pub
            pub.subscribe(onReceive, "meshtastic.receive")
            logger.info(f"Connected via TCP on {args.tcp_host}")
        else:
            from meshtastic import serial_interface
            iface = serial_interface.SerialInterface()
            iface.onReceive = onReceive
            logger.info("Connected via Serial.")
    except Exception as e:
        logger.error(f"Connection error: {e}")
        sys.exit(1)

# ---------------------- Post-Processing Pipeline ----------------------
def filter_sort_concatenate_messages():
    """Filters messages by header, sorts numerically, and concatenates."""
    global combined_messages
    logger.info("Filtering, sorting, and concatenating received messages...")

    with state_lock:
        sorted_messages = sorted(received_messages.items())  # Sort by header number
        combined_messages = [msg[1] for msg in sorted_messages]

    # Write final combined messages to log for verification
    with open("combined_messages.log", "w") as log_file:
        log_file.write("\n".join(combined_messages))

    logger.info(f"Concatenation complete. Total combined characters: {len(''.join(combined_messages))}")

def decode_and_save_image():
    """Decodes Base64 and decompresses Gzip."""
    logger.info("Decoding Base64 and decompressing Gzip...")
    combined_data = "".join(combined_messages)

    try:
        padded_base64 = combined_data.ljust((len(combined_data) + 3) // 4 * 4, "=")  # Ensure valid Base64 padding
        decoded = base64.b64decode(padded_base64)
        decompressed = gzip.decompress(decoded)

        with open(args.output, "wb") as f:
            f.write(decompressed)

        logger.info(f"Image saved to {args.output}")
    except Exception as e:
        logger.error(f"Error decoding image: {e}")
        sys.exit(1)

def upload_image():
    """Uploads image via rsync."""
    remote_path = f"{args.remote_target.rstrip('/')}/{time.strftime('%Y%m%d%H%M%S')}-restored.jpg"
    try:
        subprocess.check_call(["rsync", "-vz", "-e", f"ssh -i {args.ssh_key}", args.output, remote_path])
        logger.info(f"Image uploaded to {remote_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Upload error: {e}")
        sys.exit(1)

# ---------------------- Signal Handler ----------------------
def signal_handler(sig, frame):
    """Gracefully stops message collection but continues processing."""
    logger.info("CTRL+C detected. Stopping message collection, continuing processing...")
    global running
    running = False  # Stop the loop but continue post-processing

# ---------------------- Main Execution Flow ----------------------
def main():
    global args, running
    parser = argparse.ArgumentParser(description="Meshtastic Receiver with Filtering & Processing")
    parser.add_argument("--sender_node_id", required=True, help="Sender node ID to filter messages from.")
    parser.add_argument("--run_time", type=int, required=True, help="Run time before script terminates (minutes).")
    parser.add_argument("--header", type=str, default="pn", help="Expected message prefix (default: 'pn').")
    parser.add_argument("--output", type=str, default="restored.jpg", help="Output image file.")
    parser.add_argument("--remote_target", type=str, required=True, help="Remote path for image upload.")
    parser.add_argument("--ssh_key", type=str, required=True, help="SSH identity file for rsync.")
    parser.add_argument("--poll_interval", type=int, default=10, help="Seconds between status checks.")
    parser.add_argument("--inactivity_timeout", type=int, default=60, help="Timeout (seconds) if no new messages arrive.")
    parser.add_argument("--connection", type=str, choices=["tcp", "serial"], required=True, help="Connection type.")
    parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost).")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode for detailed logging.")

    args = parser.parse_args()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    connect_meshtastic()
    while running and time.time() < start_time + args.run_time * 60:
        time.sleep(args.poll_interval)

    running = False
    if iface:
        iface.close()

    filter_sort_concatenate_messages()
    decode_and_save_image()
    upload_image()

    # Summary of execution
    total_runtime = time.time() - start_time
    logger.info(f"Process complete. Runtime: {total_runtime:.2f} seconds, Total messages received: {len(received_messages)}, Highest header processed: {highest_header}")

if __name__ == "__main__":
    main()
