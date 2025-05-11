#!/usr/bin/env python3
"""
Meshtastic Receiver

This script provides a robust pipeline for receiving data over a Meshtastic mesh network. 
It supports receiving and reconstructing data sent in chunks, including images, files, or simple messages.

### Purpose:
1. **Receive and Reconstruct Data**:
   - Listens for incoming messages over the Meshtastic network.
   - Reconstructs data sent in chunks, including images, files, or plain text messages.
   - Supports acknowledgment (ACK) for reliable data transfer.

2. **File Upload**:
   - Optionally uploads the reconstructed file to a remote server using `rsync`.

3. **Inactivity Timeout**:
   - Automatically stops listening after a specified period of inactivity.

### Parameters:
  - `--output`: Path to save the reconstructed file or message (default: restored.jpg).
  - `--remote_target`: Remote path for file upload (required if `--upload` is set).
  - `--ssh_key`: SSH identity file for rsync (required if `--upload` is set).
  - `--upload`: Enables uploading of the reconstructed file using rsync.
  - `--expected_messages`: Total number of expected messages to receive (required).
  - `--sender`: Node ID of the sender to filter incoming messages (optional).
  - `--run_time`: Total time in seconds to listen for incoming messages (default: 60).
  - `--inactivity_timeout`: Time in seconds to stop listening after inactivity (default: 120).
  - `--header`: Header template to identify and reconstruct chunks (use `#` as digit placeholders).
  - `--debug`: Enables debug mode for detailed logging.

### Usage Examples:

1. **Receive and Save an Image**:
   ```bash
   python3 meshtastic_receiver.py --output restored.jpg --run_time 60 --inactivity_timeout 120 --expected_messages 100 --header nc
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
          args: Command-line arguments (contains sender, header, etc.).
        """
        self.args = args
        self.received_messages = {}     # Dictionary mapping header number to full message text.
        self.duplicate_count = 0        # Count of duplicate messages received.
        self.combined_messages = []     # List of payload strings (after header removal).
        self.state_lock = Lock()        # Lock to protect shared state.
        self.running = True             # Controls the main loop execution.
        self.iface = None               # Meshtastic interface object.
        self.last_message_time = time.time()  # Timestamp of the last received message.
        self.start_time = time.time()   # Timestamp marking script start.
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
            ("sender", self.args.sender),
            ("header", self.args.header),
            ("output", self.args.output),
            ("remote_target", self.args.remote_target),
            ("ssh_key", self.args.ssh_key),
            ("poll_interval (sec)", self.args.poll_interval),
            ("inactivity_timeout (sec)", self.args.inactivity_timeout),
            ("connection", self.args.connection),
            ("tcp_host", self.args.tcp_host),
            ("upload", self.args.upload),
            ("debug", self.args.debug),
        ]
        self.print_table("Startup Summary", params)

    def print_execution_summary(self, total_runtime, total_msgs, missing_msgs, file_size):
        """
        Prints an execution summary after processing.

        Args:
          total_runtime (float): Total running time in seconds.
          total_msgs (int): Total unique messages received.
          missing_msgs (int): Estimated number of missing messages.
          file_size (int or str): Transferred file size in bytes or "N/A" if not applicable.
        """
        stats = [
            ("Total Runtime (sec)", f"{total_runtime:.2f}"),
            ("Total Unique Messages", total_msgs),
            ("Duplicate Messages", self.duplicate_count),
            ("Estimated Missing Msgs", missing_msgs),
            ("Transferred File Size (bytes)", file_size),
        ]
        self.print_table("Execution Summary", stats)

    def onReceive(self, packet, interface=None):
        """
        Callback to process an incoming message packet.

        Filters the incoming packet based on:
          - sender (the original filtering parameter).
          - The message header (it must start with the expected header string).

        After validation, it extracts the numeric header and stores the full message.
        """
        try:
            # Check that the message originates from the expected sender.
            raw_sender = packet.get("fromId")
            if not raw_sender or raw_sender.lstrip("!") != self.args.sender:
                logger.debug(f"Ignored message from sender '{raw_sender}'; expected sender '{self.args.sender}'.")
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

            # Remove the header by splitting on the first "!" character.
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
                    logger.info(f"Stored message {header_part}! from sender {self.args.sender}.")
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

    def decode_and_save_file(self):
        """
        Decodes the concatenated Base64 payload and decompresses the gzip data,
        then saves the result to an output file.
        """
        logger.info("Decoding Base64 and decompressing Gzip...")
        combined_data = "".join(self.combined_messages)
        try:
            # Ensure valid Base64 by adding required padding.
            padded_base64 = combined_data.ljust((len(combined_data) + 3) // 4 * 4, "=")
            decoded = base64.b64decode(padded_base64)
            decompressed = gzip.decompress(decoded)
            with open(self.args.output, "wb") as f:
                f.write(decompressed)
            logger.info(f"File saved to {self.args.output}")
        except Exception as e:
            logger.error(f"Error during decoding/decompression: {e}")
            sys.exit(1)

    def upload_file(self):
        """
        Uploads the output file to a remote destination using rsync.

        The command is executed with a lower CPU priority using 'nice'
        and is retried up to three times.

        This step only runs if the --upload flag is set.
        """
        remote_path = f"{self.args.remote_target.rstrip('/')}/{time.strftime('%Y%m%d%H%M%S')}-{os.path.basename(self.args.output)}"
        cmd = ["nice", "-n", "10", "rsync", "-vz", "-e", f"ssh -i {self.args.ssh_key}", self.args.output, remote_path]
        for attempt in range(1, 4):
            try:
                subprocess.check_call(cmd)
                logger.info(f"File uploaded to {remote_path}")
                return
            except subprocess.CalledProcessError as e:
                logger.error(f"Attempt {attempt}: Upload error: {e}")
                time.sleep(3)
        logger.error("Upload failed after 3 attempts.")
        sys.exit(1)

    async def run(self):
        """
        Runs the main asynchronous loop until the specified run_time or inactivity timeout is reached.

        This loop periodically checks progress. After collection stops, it:
          - Combines the message payloads.
          - If --upload is set, performs the file upload.
          - Prints the execution summary.
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
                remaining_time = end_time - now
                logger.info(
                    f"Progress: {total_msgs} messages received, expected: {self.args.expected_messages}, "
                    f"time remaining: {remaining_time:.1f} sec"
                )
                self.last_progress_time = now

            # Stop if all expected messages are received
            with self.state_lock:
                if len(self.received_messages) >= self.args.expected_messages:
                    logger.info("All expected messages received. Ending collection.")
                    self.running = False
                    break

            await asyncio.sleep(0.5)

        # Attempt graceful shutdown of the Meshtastic interface.
        if self.iface:
            try:
                self.iface.close()
            except Exception as e:
                logger.debug(f"Error closing interface: {e}")

        # Process collected messages.
        self.combine_messages()
        self.decode_and_save_file()

        if self.args.upload:
            self.upload_file()
        else:
            logger.info("Skipping file upload because --upload flag is not set.")

        total_runtime = time.time() - self.start_time
        with self.state_lock:
            total_msgs = len(self.received_messages)
        missing_msgs = self.args.expected_messages - total_msgs if self.args.expected_messages > total_msgs else 0
        if os.path.exists(self.args.output):
            file_size = os.path.getsize(self.args.output)
        else:
            file_size = "N/A"
        self.print_execution_summary(total_runtime, total_msgs, missing_msgs, file_size)


# ---------------------- Signal Handling ----------------------
def setup_signal_handlers(processor):
    """
    Sets up handlers for SIGINT and SIGTERM so that the processor can shutdown gracefully.

    When triggered, the running flag is set to False.
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
    parser.add_argument("-r","--run_time", type=int, default=60, help="Run time in minutes.")
    parser.add_argument("-s","--sender", default='eb314389', help="Sender node ID to filter messages from.")
    parser.add_argument("-h","--header", type=str, default="nc", help="Expected message header prefix (before '!').")
    parser.add_argument("-o","--output", type=str, default="restored.jpg", help="Output file.")
    parser.add_argument("-rt","--remote_target", type=str, help="Remote path for file upload.")
    parser.add_argument("-k","--ssh_key", type=str, help="SSH identity file for rsync.")
    parser.add_argument("-p","--poll_interval", type=int, default=10, help="Poll interval in seconds.")
    parser.add_argument("-i","--inactivity_timeout", type=int, default=120, help="Inactivity timeout in seconds.")
    parser.add_argument("-c","--connection", type=str, default="tcp", choices=["tcp", "serial"], help="Connection mode.")
    parser.add_argument("-t","--tcp_host", type=str, default="localhost", help="TCP host (default: localhost).")
    parser.add_argument("-d","--debug", action="store_true", help="Enable debug mode for detailed logging.")
    parser.add_argument("-u","--upload", action="store_true", help="If set, upload the processed file using rsync.")
    parser.add_argument("-e","--expected_messages", type=int, required=True, help="Total number of expected messages.")
    args = parser.parse_args()

    configure_logging(args.debug)
    processor = MeshtasticProcessor(args)
    processor.print_table("Startup Summary", [
        ("run_time (min)", args.run_time),
        ("sender", args.sender),
        ("header", args.header),
        ("output", args.output),
        ("remote_target", args.remote_target),
        ("ssh_key", args.ssh_key),
        ("poll_interval (sec)", args.poll_interval),
        ("inactivity_timeout (sec)", args.inactivity_timeout),
        ("connection", args.connection),
        ("tcp_host", args.tcp_host),
        ("upload", args.upload),
        ("expected_messages", args.expected_messages),
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
