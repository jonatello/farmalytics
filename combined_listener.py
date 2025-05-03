#!/usr/bin/env python3
"""
Meshtastic Receiver & Processor

This script:
  - Encapsulates all functionality in the MeshtasticProcessor class.
  - Uses an asynchronous main loop (via asyncio) to avoid busy-waiting.
  - Consolidates ASCII table printing into a single helper (print_table()).
  - Filters incoming messages based on the sender_node_id and a message header.
  - Combines Base64 payloads from messages (after stripping off everything up to and including the first "!" character).
  - Decodes the concatenated Base64 string, decompresses the gzip data, writes an image file,
    and uploads that file using rsync (with lowered CPU priority).
  - Displays a performance summary (including file size transferred) at the end.

Usage:
  python3 this_script.py --run_time <minutes> --sender_node_id <id> --header <prefix> \
    --output restored.jpg --remote_target <remote_path> --ssh_key <path> --connection tcp \
    --tcp_host localhost [--poll_interval 10] [--inactivity_timeout 60] [--debug]

Note: sender_node_id is the original node identifier used for filtering messages.
"""

import argparse
import asyncio
import base64
import gzip
import logging
import os
import re
import signal
import subprocess
import sys
import time
from threading import Lock

# ---------------------- Simplified Logging Configuration ----------------------
def configure_logging(debug_mode):
    """
    Configures logging to stream to stdout and write to a file.
    
    Args:
      debug_mode (bool): If True, set log level to DEBUG; otherwise, INFO.
    """
    log_level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("debug_messages.log")
        ]
    )

logger = logging.getLogger("MeshtasticReceiver")


# ---------------------- MeshtasticProcessor Class ----------------------
class MeshtasticProcessor:
    def __init__(self, args):
        """
        Initializes the processor with the provided arguments.
        
        Args:
          args: Command-line arguments (contains sender_node_id, header, etc.).
        """
        self.args = args
        self.received_messages = {}     # Dictionary mapping header number to full message text.
        self.duplicate_count = 0         # Count of duplicate messages received.
        self.combined_messages = []      # List of payload strings (after header removal).
        self.state_lock = Lock()         # Lock to protect shared state.
        self.running = True              # Controls the main loop execution.
        self.iface = None                # Meshtastic interface object.
        self.last_message_time = time.time()  # Timestamp of the last received message.
        self.highest_header = 0          # Highest header number seen so far.
        self.start_time = time.time()    # Timestamp marking script start.
        self.header_digit_pattern = re.compile(r"\d+")  # Precompiled regex for extracting digits from header.
        self.last_progress_time = time.time()  # Timestamp for progress updates.

    def print_table(self, title, items):
        """
        Prints an ASCII table with a title and key-value pairs.
        
        Args:
          title (str): The title of the table.
          items (list[tuple]): A list of (key, value) tuples to display.
        """
        table_width1 = 30
        table_width2 = 50
        separator = "+" + "-" * table_width1 + "+" + "-" * table_width2 + "+"
        title_line = "| {:^{w1}} | {:^{w2}} |".format(title, "", w1=table_width1 - 2, w2=table_width2 - 2)
        print(separator)
        print(title_line)
        print(separator)
        for key, value in items:
            print("| {:<{w1}} | {:<{w2}} |".format(key, str(value), w1=table_width1 - 2, w2=table_width2 - 2))
        print(separator)

    def print_startup_summary(self):
        """
        Prints a startup summary of the provided command-line parameters.
        """
        params = [
            ("run_time (min)", self.args.run_time),
            ("sender_node_id", self.args.sender_node_id),
            ("header", self.args.header),
            ("output", self.args.output),
            ("remote_target", self.args.remote_target),
            ("ssh_key", self.args.ssh_key),
            ("poll_interval (sec)", self.args.poll_interval),
            ("inactivity_timeout (sec)", self.args.inactivity_timeout),
            ("connection", self.args.connection),
            ("tcp_host", self.args.tcp_host),
            ("debug", self.args.debug),
        ]
        self.print_table("Startup Summary", params)

    def print_performance_summary(self, total_runtime, total_msgs, missing_msgs, file_size):
        """
        Prints a performance summary after processing.
        
        Args:
          total_runtime (float): Total running time in seconds.
          total_msgs (int): Total unique messages received.
          missing_msgs (int): Estimated number of missing messages.
          file_size (int): Transferred file size in bytes.
        """
        stats = [
            ("Total Runtime (sec)", f"{total_runtime:.2f}"),
            ("Total Unique Messages", total_msgs),
            ("Highest Header Processed", self.highest_header),
            ("Duplicate Messages", self.duplicate_count),
            ("Estimated Missing Msgs", missing_msgs),
            ("Transferred File Size (bytes)", file_size),
        ]
        self.print_table("Performance Summary", stats)

    def onReceive(self, packet, interface=None):
        """
        Callback to process an incoming message packet.

        Filters the incoming packet based on:
          - sender_node_id (the original filtering parameter).
          - The message header (it must start with the expected header string).

        After validation, it extracts the numeric header and stores the full message.
        """
        try:
            # Check that the message originates from the expected sender_node_id.
            raw_sender = packet.get("fromId")
            if not raw_sender or raw_sender.lstrip("!") != self.args.sender_node_id:
                logger.debug(f"Ignored message from sender '{raw_sender}'; expected sender_node_id '{self.args.sender_node_id}'.")
                return

            # Extract and sanitize the message text.
            text = (packet.get("decoded", {}).get("text", "").strip() or
                    packet.get("text", "").strip())
            if not text:
                logger.debug("Ignored packet with no text.")
                return

            # Ensure the message begins with the expected header.
            if not text.startswith(self.args.header):
                logger.debug(f"Ignored message because it does not start with '{self.args.header}': {text}")
                return

            # Remove the header by splitting on the first "!".
            if "!" in text:
                header_part, _ = text.split("!", 1)
            else:
                header_part = text

            # Extract the numeric portion from the header using the precompiled regex.
            match = self.header_digit_pattern.search(header_part)
            if match:
                header_num = int(match.group())
            else:
                logger.debug(f"Unable to extract header number from '{header_part}' in message: {text}")
                return

            with self.state_lock:
                if header_num in self.received_messages:
                    self.duplicate_count += 1
                    logger.debug(f"Ignored duplicate message: {header_part}!")
                else:
                    self.received_messages[header_num] = text
                    logger.info(f"Stored message {header_part}! from sender {self.args.sender_node_id}.")
                    if header_num > self.highest_header:
                        self.highest_header = header_num
                        logger.info(f"Updated highest header to {self.highest_header}.")
                    self.last_message_time = time.time()

        except Exception as e:
            logger.error(f"Exception in onReceive: {e}")

    def connect_meshtastic(self):
        """
        Establishes a connection to the Meshtastic device using either TCP or serial.

        The connection mode is selected based on the command-line argument.
        """
        logger.info("Connecting to Meshtastic device...")
        try:
            if self.args.connection == "tcp":
                from meshtastic.tcp_interface import TCPInterface
                self.iface = TCPInterface(hostname=self.args.tcp_host)
                from pubsub import pub
                pub.subscribe(self.onReceive, "meshtastic.receive")
                logger.info(f"Connected via TCP on {self.args.tcp_host}")
            else:
                from meshtastic import serial_interface
                self.iface = serial_interface.SerialInterface()
                self.iface.onReceive = self.onReceive
                logger.info("Connected via Serial.")
        except Exception as e:
            logger.error(f"Connection error: {e}")
            sys.exit(1)

    def combine_messages(self):
        """
        Combines the received messages into a single payload string.

        This method:
          - Sorts the messages by header number.
          - Strips off the header (everything up to and including the first "!") from each message.
        """
        with self.state_lock:
            sorted_items = sorted(self.received_messages.items())
            self.combined_messages = []
            for _, msg in sorted_items:
                if "!" in msg:
                    payload = msg.split("!", 1)[1]
                    self.combined_messages.append(payload)
                else:
                    self.combined_messages.append(msg)

    def decode_and_save_image(self):
        """
        Concatenates the payload strings, decodes the Base64 content, decompresses the gzip data,
        and saves the result to an output image file.
        """
        logger.info("Decoding Base64 and decompressing Gzip...")
        combined_data = "".join(self.combined_messages)
        try:
            padded_base64 = combined_data.ljust((len(combined_data) + 3) // 4 * 4, "=")
            decoded = base64.b64decode(padded_base64)
            decompressed = gzip.decompress(decoded)
            with open(self.args.output, "wb") as f:
                f.write(decompressed)
            logger.info(f"Image saved to {self.args.output}")
        except Exception as e:
            logger.error(f"Error during decoding/decompression: {e}")
            sys.exit(1)

    def upload_image(self):
        """
        Uploads the output image file to a remote destination using rsync.

        Runs the command with a lower CPU priority using 'nice' and retries up to three times.
        """
        remote_path = f"{self.args.remote_target.rstrip('/')}/{time.strftime('%Y%m%d%H%M%S')}-restored.jpg"
        cmd = ["nice", "-n", "10", "rsync", "-vz", "-e", f"ssh -i {self.args.ssh_key}", self.args.output, remote_path]
        for attempt in range(1, 4):
            try:
                subprocess.check_call(cmd)
                logger.info(f"Image uploaded to {remote_path}")
                return
            except subprocess.CalledProcessError as e:
                logger.error(f"Attempt {attempt}: Upload error: {e}")
                time.sleep(3)
        logger.error("Upload failed after 3 attempts.")
        sys.exit(1)

    async def run(self):
        """
        Runs the main asynchronous loop until the run_time or inactivity timeout is reached.

        This loop periodically checks for progress, and once complete, it:
          - Combines message payloads.
          - Decodes and saves the image.
          - Uploads the image.
          - Prints a performance summary.
        """
        self.connect_meshtastic()
        end_time = self.start_time + self.args.run_time * 60

        logger.info("Entering main processing loop...")
        while self.running and time.time() < end_time:
            now = time.time()
            if now - self.last_message_time > self.args.inactivity_timeout:
                logger.info("Inactivity timeout reached. Ending collection.")
                self.running = False
                break

            if now - self.last_progress_time >= self.args.poll_interval:
                with self.state_lock:
                    total_msgs = len(self.received_messages)
                    current_highest = self.highest_header
                remaining_time = end_time - now
                logger.info(
                    f"Progress: {total_msgs} messages, highest header: {current_highest}, time remaining: {remaining_time:.1f} sec"
                )
                self.last_progress_time = now

            await asyncio.sleep(0.5)

        # Attempt graceful shutdown of the Meshtastic interface.
        if self.iface:
            try:
                self.iface.close()
            except Exception as e:
                logger.debug(f"Error closing interface: {e}")

        # Process the collected messages and upload the image.
        self.combine_messages()
        self.decode_and_save_image()
        self.upload_image()

        total_runtime = time.time() - self.start_time
        with self.state_lock:
            total_msgs = len(self.received_messages)
        missing_msgs = self.highest_header - total_msgs if self.highest_header > total_msgs else 0
        file_size = os.path.getsize(self.args.output)
        self.print_table("Performance Summary", [
            ("Total Runtime (sec)", f"{total_runtime:.2f}"),
            ("Total Unique Messages", total_msgs),
            ("Highest Header Processed", self.highest_header),
            ("Duplicate Messages", self.duplicate_count),
            ("Estimated Missing Msgs", missing_msgs),
            ("Transferred File Size (bytes)", file_size)
        ])


# ---------------------- Signal Handling ----------------------
def setup_signal_handlers(processor):
    """
    Sets up signal handlers for SIGINT and SIGTERM to allow for graceful shutdown.

    When triggered, the handler sets the running flag to False.
    """
    def handler(sig, frame):
        logger.info("CTRL+C detected. Initiating shutdown...")
        processor.running = False
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


# ---------------------- Main Entry Point ----------------------
def main():
    """
    Parses command-line arguments, configures logging, and initializes the MeshtasticProcessor.

    Sets up signal handlers and starts the asynchronous processing loop.
    """
    parser = argparse.ArgumentParser(
        description="Meshtastic Receiver with Asynchronous Processing and Robust Error Handling"
    )
    parser.add_argument("--run_time", type=int, required=True, help="Run time in minutes.")
    parser.add_argument("--sender_node_id", required=True, help="Sender node ID to filter messages from.")
    parser.add_argument("--header", type=str, default="pn", help="Expected message header prefix (before '!').")
    parser.add_argument("--output", type=str, default="restored.jpg", help="Output image file.")
    parser.add_argument("--remote_target", type=str, required=True, help="Remote path for image upload.")
    parser.add_argument("--ssh_key", type=str, required=True, help="SSH identity file for rsync.")
    parser.add_argument("--poll_interval", type=int, default=10, help="Poll interval in seconds.")
    parser.add_argument("--inactivity_timeout", type=int, default=60, help="Inactivity timeout in seconds.")
    parser.add_argument("--connection", type=str, choices=["tcp", "serial"], required=True, help="Connection mode.")
    parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost).")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode for detailed logging.")
    args = parser.parse_args()

    configure_logging(args.debug)
    processor = MeshtasticProcessor(args)
    processor.print_table("Startup Summary", [
        ("run_time (min)", args.run_time),
        ("sender_node_id", args.sender_node_id),
        ("header", args.header),
        ("output", args.output),
        ("remote_target", args.remote_target),
        ("ssh_key", args.ssh_key),
        ("poll_interval (sec)", args.poll_interval),
        ("inactivity_timeout (sec)", args.inactivity_timeout),
        ("connection", args.connection),
        ("tcp_host", args.tcp_host),
        ("debug", args.debug),
    ])
    setup_signal_handlers(processor)

    try:
        asyncio.run(processor.run())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
