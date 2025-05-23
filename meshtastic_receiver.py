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
from threading import Lock, Event
import atexit

from pubsub import pub

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


# ---------------------- PersistentMeshtasticReceiver Class ----------------------
from meshtastic.tcp_interface import TCPInterface
from meshtastic.serial_interface import SerialInterface

class PersistentMeshtasticReceiver:
    def __init__(self, args):
        """
        Initializes the receiver with the provided arguments.

        Args:
          args: Command-line arguments (contains sender, header, etc.).
        """
        self.args = args
        self.connection = args.connection
        self.received_messages = {}     # Dictionary mapping header number to full message text.
        self.duplicate_count = 0        # Count of duplicate messages received.
        self.combined_messages = []     # List of payload strings (after header removal).
        self.state_lock = Lock()        # Lock to protect shared state.
        self.running = True             # Controls the main loop execution.
        self.last_message_time = time.time()  # Timestamp of the last received message.
        self.start_time = time.time()   # Timestamp marking script start.
        self.header_digit_pattern = re.compile(r"\d+")  # Precompiled regex for extracting digits from header.
        self.last_progress_time = time.time()  # Timestamp for progress updates.
        self.interface = None
        self.termination_event = Event()  # Add termination event

    def __enter__(self):
        """Context manager entry point: Open the connection."""
        self.open_connection()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Context manager exit point: Close the connection."""
        self.close_connection()

    def open_connection(self, tcp_host="localhost"):
        retries = 5
        for attempt in range(1, retries + 1):
            try:
                if self.connection == 'tcp':
                    logger.info(f"Attempting to establish TCP connection (Attempt {attempt}/{retries})...")
                    self.interface = TCPInterface(hostname=tcp_host)
                elif self.connection == 'serial':
                    logger.info(f"Attempting to establish Serial connection (Attempt {attempt}/{retries})...")
                    self.interface = SerialInterface()
                else:
                    logger.error(f"Unknown connection type: {self.connection}")
                    sys.exit(1)

                # Subscribe to the 'meshtastic.receive' topic
                pub.subscribe(self.on_receive, "meshtastic.receive")
                logger.info("Subscribed to 'meshtastic.receive' topic.")
                logger.info("Persistent connection established.")
                time.sleep(2)  # Ensure the connection is stable
                return
            except Exception as e:
                logger.error(f"Error establishing connection (Attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(2)
                else:
                    logger.error("Failed to establish connection after multiple attempts. Exiting.")
                    self.cleanup()
                    sys.exit(1)

    def close_connection(self):
        """Closes the persistent Meshtastic connection."""
        try:
            if self.interface:
                logger.info("Stopping Meshtastic threads...")
                if hasattr(self.interface, "stop"):
                    try:
                        self.interface.stop(timeout=10)  # Gracefully stop threads with a timeout
                        logger.info("Stopped all Meshtastic threads.")
                    except TimeoutError:
                        logger.warning("Timeout while stopping Meshtastic threads. Forcing connection close.")
                    except Exception as e:
                        logger.error(f"Error stopping threads: {e}")
                self.interface.close()
                logger.info("Persistent connection closed.")
        except BrokenPipeError:
            logger.warning("Broken pipe detected during connection close.")
        except Exception as e:
            logger.error(f"Error closing connection: {e}")
        finally:
            self.interface = None

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

    def on_receive(self, packet, interface=None):
        try:
            logger.debug(f"Received packet: {packet}")

            raw_sender = packet.get("fromId")
            if self.args.sender and (not raw_sender or raw_sender.lstrip("!") != self.args.sender):
                logger.info(f"Ignored message from sender '{raw_sender}'; expected sender '{self.args.sender}'.")
                return

            text = (packet.get("decoded", {}).get("text", "").strip() or packet.get("text", "").strip())
            if not text:
                logger.debug("Ignored packet with no text.")
                return

            if not text.startswith(self.args.header):
                logger.info(f"Ignored message because it does not start with '{self.args.header}': {text}")
                return

            if "!" in text:
                header_part, payload = text.split("!", 1)
            else:
                header_part = text
                payload = ""

            logger.debug(f"Header part: {header_part}, Payload: {payload}")

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
                    self.received_messages[header_num] = payload
                    logger.info(f"Stored message {header_part}! from sender '{raw_sender}'.")
                    self.last_message_time = time.time()

        except Exception as e:
            logger.error(f"Exception in on_receive: {e}")

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

    def check_progress_and_timeout(self, now, end_time):
        if now - self.last_message_time > self.args.inactivity_timeout:
            logger.info("Inactivity timeout reached. Ending collection.")
            self.running = False
            return False

        if now - self.last_progress_time >= self.args.poll_interval:
            with self.state_lock:
                total_msgs = len(self.received_messages)
            remaining_time = end_time - now
            logger.info(
                f"Progress: {total_msgs} messages received, expected: {self.args.expected_messages}, "
                f"time remaining: {remaining_time:.1f} sec"
            )
            self.last_progress_time = now
        return True

    async def run(self):
        self.open_connection()

        logger.info("Entering main processing loop...")
        end_time = self.start_time + self.args.run_time * 60

        while self.running and not self.termination_event.is_set() and time.time() < end_time:
            now = time.time()
            if not self.check_progress_and_timeout(now, end_time):
                break

            # Stop if all expected messages are received
            with self.state_lock:
                if len(self.received_messages) >= self.args.expected_messages:
                    logger.info("All expected messages received. Ending collection.")
                    self.running = False
                    break

            try:
                self.interface.sendHeartbeat()
            except BrokenPipeError:
                logger.warning("Broken pipe detected. Reconnecting...")
                self.close_connection()
                self.open_connection()

            await asyncio.sleep(0.5)

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
        file_size = os.path.getsize(self.args.output) if os.path.exists(self.args.output) else "N/A"
        self.print_execution_summary(total_runtime, total_msgs, missing_msgs, file_size)

        self.cleanup()

    def cleanup(self):
        """Cleans up resources and closes the connection."""
        if self.interface:
            try:
                logger.info("Cleaning up Meshtastic connection...")
                self.close_connection()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")


# ---------------------- Signal Handling for Receiving ----------------------
def setup_signal_handlers(receiver):
    def handler(sig, frame):
        logger.info(f"Signal {sig} detected. Closing connection...")
        receiver.termination_event.set()  # Signal termination
        receiver.cleanup()
        sys.exit(0)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

# ---------------------- Main Entry Point ----------------------
def main():
    """
    Parses command-line arguments, configures logging, and initializes the PersistentMeshtasticReceiver.

    Sets up signal handlers and starts the asynchronous processing loop.
    """
    parser = argparse.ArgumentParser(
        description="Meshtastic Receiver with Asynchronous Processing and Robust Error Handling"
    )
    parser.add_argument("-r","--run_time", type=int, default=60, help="Run time in minutes.")
    parser.add_argument("-s","--sender", type=str, help="Sender node ID to filter messages from.")
    parser.add_argument("-he","--header", type=str, default="nc", help="Expected message header prefix (before '!').")
    parser.add_argument("-o","--output", type=str, default="restored.jpg", help="Output file.")
    parser.add_argument("-rt","--remote_target", type=str, default="jonatello@192.168.2.4:/mnt/RaidZ/Master/Pictures/Motion/farmalytics3/", help="Remote path for file upload.")
    parser.add_argument("-k","--ssh_key", type=str, help="SSH identity file for rsync.")
    parser.add_argument("-p","--poll_interval", type=int, default=10, help="Poll interval in seconds.")
    parser.add_argument("-i","--inactivity_timeout", type=int, default=120, help="Inactivity timeout in seconds.")
    parser.add_argument("-c","--connection", type=str, choices=["tcp", "serial"], default="tcp", help="Connection mode.")
    parser.add_argument("-t","--tcp_host", type=str, default="localhost", help="TCP host (default: localhost).")
    parser.add_argument("-d","--debug", action="store_true", help="Enable debug mode for detailed logging.")
    parser.add_argument("-u","--upload", action="store_true", help="If set, upload the processed file using rsync.")
    parser.add_argument("-e","--expected_messages", type=int, required=True, help="Total number of expected messages.")
    args = parser.parse_args()

    configure_logging(args.debug)
    receiver = PersistentMeshtasticReceiver(args)
    atexit.register(receiver.cleanup)
    receiver.print_table("Startup Summary", [
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
    setup_signal_handlers(receiver)

    try:
        asyncio.run(receiver.run())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
