#!/usr/bin/env python3
"""
Optimized Meshtastic Receiver & Processor with Real-Time Tracking,
In-Memory Filtering, Periodic Progress Updates, and a Simplified
End-of-Run Performance Breakdown.

Supports TCP and Serial connections.
"""

import argparse
import base64
import gzip
import logging
import os
import re
import signal
import subprocess
import sys
import time

# ---------------------- Logging Configuration ----------------------
logger = logging.getLogger("MeshtasticReceiver")
logger.setLevel(logging.DEBUG)
logger.propagate = False

# Merged logging to a single file (all levels)
file_handler = logging.FileHandler("debug_messages.log")
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
file_handler.setLevel(logging.DEBUG)
logger.addHandler(file_handler)

# Console handler (user-facing output)
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# ---------------------- Global State ----------------------
received_messages = {}  # Mapping header number -> full message text
duplicate_count = 0     # Count of duplicate messages (re-transmissions)
combined_messages = []  # In-memory list for combined payload parts
state_lock = __import__("threading").Lock()
running = True
iface = None
last_message_time = time.time()
highest_header = 0
start_time = time.time()

# ---------------------- Utility: ASCII Table for Startup Summary ----------------------
def print_startup_summary(args):
    table_width1 = 30
    table_width2 = 50
    separator = "+" + "-" * table_width1 + "+" + "-" * table_width2 + "+"
    header_line = "| {:<{w1}} | {:<{w2}} |".format("Parameter", "Value", w1=table_width1 - 2, w2=table_width2 - 2)
    print(separator)
    print(header_line)
    print(separator)
    parameters = [
        ("sender_node_id", args.sender_node_id),
        ("run_time (min)", args.run_time),
        ("header", args.header),
        ("output", args.output),
        ("remote_target", args.remote_target),
        ("ssh_key", args.ssh_key),
        ("poll_interval (sec)", args.poll_interval),
        ("inactivity_timeout (sec)", args.inactivity_timeout),
        ("connection", args.connection),
        ("tcp_host", args.tcp_host),
        ("debug", args.debug),
    ]
    for key, value in parameters:
        print("| {:<{w1}} | {:<{w2}} |".format(key, str(value), w1=table_width1 - 2, w2=table_width2 - 2))
    print(separator + "\n")

# ---------------------- Message Reception Callback ----------------------
def onReceive(packet, interface=None):
    global last_message_time, highest_header, duplicate_count
    try:
        raw_sender = packet.get("fromId")
        sender = raw_sender.lstrip("!") if raw_sender else None

        if sender != args.sender_node_id:
            logger.debug(f"Ignored message from sender {raw_sender} (filter: {args.sender_node_id}).")
            return

        text = (packet.get("decoded", {}).get("text", "").strip() or
                packet.get("text", "").strip())
        if not text:
            logger.debug("Ignored packet with no text.")
            return

        # Extract header number and payload from the message.
        pattern = fr"^{re.escape(args.header)}(\d+)!"
        match = re.match(pattern, text)
        if match:
            header_num = int(match.group(1))
            with state_lock:
                if header_num in received_messages:
                    duplicate_count += 1
                    logger.debug(f"Duplicate message {args.header}{header_num} received; ignoring duplicate.")
                else:
                    received_messages[header_num] = text
                    logger.info(f"Stored message {args.header}{header_num} from sender {sender}.")
                    if header_num > highest_header:
                        highest_header = header_num
                        logger.info(f"Updated expected message count to {highest_header}.")
                    if args.debug:
                        logger.debug(f"Message details: Sender={sender}, Header={header_num}, Text={text}")
                    last_message_time = time.time()
        else:
            logger.debug(f"Ignored message not matching pattern: {text}")
    except Exception as e:
        logger.error(f"Exception in onReceive: {e}")

# ---------------------- Connection Handling ----------------------
def connect_meshtastic():
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

# ---------------------- In-Memory Message Combination ----------------------
def combine_messages():
    global combined_messages
    with state_lock:
        sorted_items = sorted(received_messages.items())  # Sorted by header number.
        # Remove the header prefix from each message.
        combined_messages = [re.sub(fr"^{re.escape(args.header)}\d+!", "", msg) for _, msg in sorted_items]

# ---------------------- Decode & Save Image ----------------------
def decode_and_save_image():
    logger.info("Decoding Base64 and decompressing Gzip...")
    combined_data = "".join(combined_messages)
    try:
        padded_base64 = combined_data.ljust((len(combined_data) + 3) // 4 * 4, "=")
        decoded = base64.b64decode(padded_base64)
        decompressed = gzip.decompress(decoded)
        with open(args.output, "wb") as f:
            f.write(decompressed)
        logger.info(f"Image saved to {args.output}")
    except Exception as e:
        logger.error(f"Error during decoding/decompression: {e}")
        sys.exit(1)

# ---------------------- Upload Image ----------------------
def upload_image():
    remote_path = f"{args.remote_target.rstrip('/')}/{time.strftime('%Y%m%d%H%M%S')}-restored.jpg"
    try:
        subprocess.check_call(["rsync", "-vz", "-e", f"ssh -i {args.ssh_key}", args.output, remote_path])
        logger.info(f"Image uploaded to {remote_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Upload error: {e}")
        sys.exit(1)

# ---------------------- Signal Handler ----------------------
def signal_handler(sig, frame):
    global running
    logger.info("CTRL+C detected. Stopping message collection and proceeding to processing...")
    running = False

# ---------------------- Main Execution Flow ----------------------
def main():
    global args, running, start_time
    parser = argparse.ArgumentParser(description="Meshtastic Receiver with In-Memory Filtering & Processing")
    parser.add_argument("--sender_node_id", required=True, help="Sender node ID to filter messages from.")
    parser.add_argument("--run_time", type=int, required=True, help="Run time before script terminates (minutes).")
    parser.add_argument("--header", type=str, default="pn", help="Expected message prefix (default: 'pn').")
    parser.add_argument("--output", type=str, default="restored.jpg", help="Output image file.")
    parser.add_argument("--remote_target", type=str, required=True, help="Remote path for image upload.")
    parser.add_argument("--ssh_key", type=str, required=True, help="SSH identity file for rsync.")
    parser.add_argument("--poll_interval", type=int, default=10, help="Poll interval (sec) for progress updates.")
    parser.add_argument("--inactivity_timeout", type=int, default=60, help="Timeout (sec) if no new messages arrive.")
    parser.add_argument("--connection", type=str, choices=["tcp", "serial"], required=True, help="Connection type.")
    parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost).")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode for detailed logging.")
    args = parser.parse_args()

    # Print startup summary as an ASCII table.
    print_startup_summary(args)
    logger.info("Startup summary printed above.")

    # Set up signal handling.
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    connect_meshtastic()

    end_time = start_time + args.run_time * 60
    last_progress_time = time.time()

    # Main loop: poll for messages, provide periodic updates, and check inactivity.
    while running and time.time() < end_time:
        now = time.time()
        # Check inactivity timeout.
        if now - last_message_time > args.inactivity_timeout:
            logger.info("Inactivity timeout reached. Ending message collection.")
            break

        # Provide a progress update every poll_interval seconds.
        if now - last_progress_time >= args.poll_interval:
            with state_lock:
                total_msgs = len(received_messages)
                current_highest = highest_header
            remaining_time = end_time - now
            logger.info(f"Progress: {total_msgs} messages captured, highest header: {current_highest}, time remaining: {remaining_time:.1f} sec")
            logger.debug(f"Progress Update: messages captured: {total_msgs}, highest header: {current_highest}, time remaining: {remaining_time:.1f} sec")
            last_progress_time = now

        time.sleep(1)

    running = False
    if iface:
        try:
            iface.close()
        except Exception as e:
            logger.debug(f"Error closing interface: {e}")

    # Combine messages (in memory), then decode, decompress, and upload the image.
    combine_messages()
    decode_and_save_image()
    upload_image()

    # End-of-run performance summary.
    total_runtime = time.time() - start_time
    with state_lock:
        total_msgs = len(received_messages)
    missing_msgs = highest_header - total_msgs if highest_header > total_msgs else 0

    summary = (
        "\n--- Performance Summary ---\n"
        f"Total Runtime: {total_runtime:.2f} seconds\n"
        f"Total Unique Messages Received: {total_msgs}\n"
        f"Highest Header Processed: {highest_header}\n"
        f"Duplicate Messages (Re-transmissions): {duplicate_count}\n"
        f"Estimated Missing Messages: {missing_msgs}\n"
        "---------------------------"
    )
    logger.info(summary)
    print(summary)

if __name__ == "__main__":
    main()
