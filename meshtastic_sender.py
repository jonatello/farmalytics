#!/usr/bin/env python3
"""
Meshtastic Sender

This script provides a flexible and robust pipeline for sending data over a Meshtastic mesh network. 
It supports three primary modes of operation: image processing and transfer, and file transfer.

### Purpose:
1. **Image Processing and Transfer**:
   - Captures a snapshot via a configured snapshot URL.
   - Optimizes and resizes the image using tools like `jpegoptim` and `ImageMagick`.
   - Compresses the image using Zopfli gzip and Base64 encodes the result.
   - Sends the processed image over the Meshtastic network.

2. **File Transfer**:
   - Compresses and Base64 encodes a specified file.
   - Sends the processed file over the Meshtastic network.

### Parameters:
  - `--mode`: Specifies the mode of operation (`image_transfer`, or `file_transfer`).
  - `--header`: Template for prepending headers to chunks (use `#` as digit placeholders).
  - `--quality`: JPEG quality factor for optimization (default: 90, used in `image_transfer` mode).
  - `--resize`: Resize dimensions for the image (e.g., `800x600`, used in `image_transfer` mode).
  - `--output`: Output file for the processed image or file (default: `base64_image.gz`).
  - `--preview_image`: Generates an ASCII preview of the image using `jp2a` (default: off).
  - `--cleanup`: Enables cleanup of intermediate files after processing (used in `image_transfer` mode).
  - `--remote_target`: Remote path for file upload (required if `--upload` is set).
  - `--ssh_key`: SSH identity file for rsync (required if `--upload` is set).
  - `--upload`: Enables uploading of the processed image or file using rsync.
  - `--file_path`: Path to the file to send (required for `file_transfer` mode).
  - `--chunk_size`: Maximum length of each chunk when sending (default: 200).
  - `--dest`: Destination Node ID for Meshtastic send (default: `!47a78d36`).
  - `--max_retries`: Maximum number of retries per chunk (default: 10).
  - `--retry_delay`: Delay in seconds between retries (default: 1).
  - `--sleep_delay`: Sleep delay in seconds between sending chunks (default: 0.1).
  - `--start_delay`: Delay in seconds after sending the initial message but before sending chunks (default: 0.0).
  - `--connection`: Connection mode (`tcp` or `serial`, default: `tcp`).
  - `--tcp_host`: TCP host for Meshtastic connection (default: `localhost`).
  - `--debug`: Enables debug mode for detailed logging.

### Usage Examples:
  --- To process an image and then upload and send it ---
  python3 meshtastic_sender.py --mode all --header nc --upload \
    --quality 75 --resize 800x600 --remote_target "user@host:/remote/path" --ssh_key "/path/to/id_rsa" \
    --chunk_size 180 --dest '!47a78d36' --connection tcp --tcp_host 192.168.1.100 --sleep_delay 1

  --- To run only the image processing pipeline and optionally upload ---
  python3 meshtastic_sender.py --mode process --quality 75 --resize 800x600 \
    --upload --remote_target "user@host:/remote/path" --ssh_key "/path/to/id_rsa"

Use `--help` for full details on all parameters.
"""

import argparse
import asyncio
import base64
import gzip
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import glob
from pathlib import Path
import requests
import zopfli.gzip
from threading import Lock
import json
import atexit

# --------- Simple ASCII Table Helper ----------
def print_table(title, items):
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
    sys.stderr.flush()
    sys.stdout.flush()

# --------- Logging Configuration ----------
def configure_logging(debug_mode):
    log_level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("debug_messages.log")
        ]
    )

logger = logging.getLogger("MeshtasticSender")

# --------- Image Processing Pipeline Function ----------
def optimize_compress_zip_base64encode_jpg(
        quality=90,
        resize="800x600",
        snapshot_url="http://localhost:8080/0/action/snapshot",
        output_file="base64_image.gz",
        cleanup=False,
        preview_image=False):  # Add preview_image as a parameter
    """
    Captures a snapshot, optimizes/resizes the JPEG, compresses it with Zopfli gzip,
    and Base64 encodes the compressed image into output_file.

    Steps:
      1. Trigger snapshot capture via snapshot_url.
      2. Wait one second for the snapshot to be written.
      3. Copy the snapshot from /var/lib/motion/lastsnap.jpg to the current directory.
      4. Remove any old snapshots from /var/lib/motion/.
      5. Optimize the JPEG using jpegoptim.
      6. Further optimize with jpegtran.
      7. Resize the image using ImageMagick's convert.
      8. Compress the file using zopfli.gzip.
      9. Base64 encode the compressed file.
     10. Remove intermediate files.

    Returns:
      dict: A summary dictionary including file sizes and total character count.
    """
    image_path = "lastsnap.jpg"
    compressed_image_path = "compressed.jpg"
    zipped_image_path = "compressed_image.gz"
    summary = {}

    print(f"Capturing snapshot from {snapshot_url} ...")
    r = requests.get(snapshot_url)
    if r.status_code != 200:
        raise RuntimeError("Snapshot capture failed with status code: " + str(r.status_code))
    
    time.sleep(1)  # Allow time for the snapshot to be written.
    
    source_snapshot = "/var/lib/motion/lastsnap.jpg"
    print(f"Copying snapshot from {source_snapshot} to {image_path} ...")
    shutil.copy2(source_snapshot, image_path)

    # Generate an ASCII preview of the image using jp2a
    if preview_image:  # Use the passed parameter instead of args.preview_image
        print(f"Generating ASCII preview of {image_path} ...")
        try:
            subprocess.run(["jp2a", "--width=80", image_path], check=True)
        except FileNotFoundError:
            print("Error: jp2a is not installed or not found in the system PATH.")
        except subprocess.CalledProcessError as e:
            print(f"Error generating ASCII preview: {e}")
    
    # Execute cleanup logic only if the cleanup flag is set
    if cleanup:
        print("Performing cleanup of old snapshots...")
        for f in glob.glob("/var/lib/motion/*"):
            try:
                os.remove(f)
            except Exception as e:
                print(f"Warning: Could not remove {f}: {e}")
    
    initial_size = os.stat(image_path).st_size
    print(f"Initial file size: {initial_size} bytes")
    
    print(f"Optimizing JPEG with quality {quality} ...")
    subprocess.run(["jpegoptim", f"--max={quality}", "--strip-all", image_path], check=True)
    
    subprocess.run(["jpegtran", "-optimize", "-progressive", "-copy", "none",
                    "-outfile", compressed_image_path, image_path], check=True)
    optimized_size = os.stat(compressed_image_path).st_size
    print(f"Size after optimization: {optimized_size} bytes")
    
    print(f"Resizing image to {resize} ...")
    subprocess.run(["convert", compressed_image_path, "-resize", resize, compressed_image_path], check=True)
    resized_size = os.stat(compressed_image_path).st_size
    print(f"Size after resizing: {resized_size} bytes")
    
    print("Compressing image using Zopfli gzip ...")
    with open(compressed_image_path, "rb") as f_in:
        data = f_in.read()
    compressed_data = zopfli.gzip.compress(data)
    with open(zipped_image_path, "wb") as f_out:
        f_out.write(compressed_data)
    zipped_size = os.stat(zipped_image_path).st_size
    print(f"Size after compression: {zipped_size} bytes")
    
    print("Encoding compressed image to Base64 ...")
    with open(zipped_image_path, "rb") as f_in:
        zipped_content = f_in.read()
    base64_encoded = base64.b64encode(zipped_content)
    with open(output_file, "wb") as f_out:
        f_out.write(base64_encoded)
    base64_size = os.stat(output_file).st_size
    print(f"Size after Base64 encoding: {base64_size} bytes")
    
    os.remove(image_path)
    os.remove(compressed_image_path)
    os.remove(zipped_image_path)
    
    print("Image processing complete. Base64 output saved to:", output_file)

# --------- File Upload Function ----------
def upload_file(file_path: str, remote_target: str, ssh_key: str):
    """
    Uploads the specified file to a remote destination using rsync with lowered priority.
    
    The remote destination is formed by appending a timestamped filename to remote_target.
    """
    remote_path = f"{remote_target.rstrip('/')}/{time.strftime('%Y%m%d%H%M%S')}-restored.jpg"
    cmd = ["nice", "-n", "10", "rsync", "-vz", "-e", f"ssh -i {ssh_key}", file_path, remote_path]
    try:
        subprocess.check_call(cmd)
        logger.info(f"File uploaded to {remote_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Upload failed: {e}")
        sys.exit(1)

# --------- Persistent Meshtastic Sender Class ----------
from meshtastic.tcp_interface import TCPInterface
from meshtastic.serial_interface import SerialInterface
from urllib.parse import urlencode
from threading import Event

class PersistentMeshtasticSender:
    """
    Uses a persistent Meshtastic connection to send file content.

    This class reads a file, splits it into chunks, and sends each chunk sequentially.
    An optional header (derived from a template) can be prepended to each chunk.
    Includes retry logic and a delay between sends.
    """
    def __init__(self, file_path: Path, chunk_size: int, dest: str,
                 connection: str, max_retries: int = 10,
                 retry_delay: int = 1.0, header_template: str = None,
                 sleep_delay: float = 0.1, start_delay: float = 0.0):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.dest = dest
        self.connection = connection.lower()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.header_template = header_template
        self.sleep_delay = sleep_delay
        self.start_delay = start_delay
        self.interface = None
        self.termination_event = Event()

    def __enter__(self):
        """Context manager entry point: Open the connection."""
        self.open_connection()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Context manager exit point: Close the connection."""
        self.close_connection()

    def read_file(self) -> str:
        try:
            return self.file_path.read_text()
        except Exception as e:
            logger.error(f"Error reading file '{self.file_path}': {e}")
            sys.exit(1)

    def get_file_size(self) -> int:
        return self.file_path.stat().st_size

    def chunk_content(self, content: str) -> list:
        return [content[i:i + self.chunk_size] for i in range(0, len(content), self.chunk_size)]

    def generate_header(self, index: int, total_chunks: int) -> str:
        if not self.header_template:
            return ""
        if '#' in self.header_template:
            pattern = re.compile(r"(#+)")
            match = pattern.search(self.header_template)
            if match:
                width = len(match.group(0))
                counter_str = f"{index:0{width}d}"
                header = pattern.sub(counter_str, self.header_template, count=1)
                if not header.endswith('!'):
                    header += "!"
                return header
            else:
                return f"{self.header_template}{index}!"
        else:
            width = len(str(total_chunks))
            header = f"{self.header_template}{index:0{width}d}!"
            return header

    def open_connection(self, tcp_host="localhost"):
        """Establishes a persistent Meshtastic connection (TCP or Serial)."""
        retries = 3
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
                logger.info("Persistent connection established.")
                return  # Exit the loop if the connection is successful
            except Exception as e:
                logger.error(f"Error establishing connection (Attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(2)  # Wait before retrying
                else:
                    logger.error("Failed to establish connection after multiple attempts. Exiting.")
                    self.close_connection()
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

    async def send_chunk(self, message: str, chunk_index: int, total_chunks: int) -> int:
        """
        Sends a single chunk (optionally prepended with a generated header) with retries.
        Returns the number of retries performed on success.
        """
        if self.header_template:
            header = self.generate_header(chunk_index, total_chunks)
            full_message = header + message
        else:
            header = ""
            full_message = message

        attempt = 0
        while attempt < self.max_retries:
            try:
                # Send the message
                self.interface.sendText(full_message, self.dest, wantAck=True)
                remaining = total_chunks - chunk_index
                logger.info(f"Sent chunk {chunk_index}/{total_chunks} with header '{header}' "
                            f"(Attempt {attempt+1}/{self.max_retries}, {remaining} remaining)")
                return attempt
            except BrokenPipeError:
                logger.warning(f"Broken pipe detected. Reconnecting... (Attempt {attempt+1}/{self.max_retries})")
                self.close_connection()
                await asyncio.sleep(2)  # Use asyncio.sleep to make it interruptible
                self.open_connection()
            except Exception as e:
                attempt += 1
                logger.warning(f"Retry {attempt}/{self.max_retries} for chunk {chunk_index} due to error: {e}")
                await asyncio.sleep(self.retry_delay)  # Use asyncio.sleep
                if attempt == self.max_retries:
                    logger.error(f"Aborting after {self.max_retries} retries for chunk {chunk_index}.")
                    sys.exit(1)
        return attempt

    def send_receiver_message(self, total_chunks: int, receiver: dict):
        """
        Sends an initial message with the header "receive!" followed by the receiver parameters.

        Args:
            total_chunks (int): The total number of chunks to be sent.
            receiver (dict): A JSON object containing receiver-specific parameters.
        """
        if self.header_template:
            header = self.header_template
        else:
            header = ""

        # Add total_chunks and header to the receiver dictionary
        receiver["expected_messages"] = total_chunks
        receiver["header"] = header

        # Handle the 'upload' parameter separately
        upload_flag = ""
        if receiver.get("upload", False):  # Check if 'upload' is explicitly set to True
            upload_flag = "upload"
            del receiver["upload"]  # Remove 'upload' from the dictionary

        # Convert the remaining receiver dictionary to a query string
        query_string = urlencode(receiver)

        # Construct the initial message with the query string and upload flag
        if upload_flag:
            initial_message = f"receive!{upload_flag}&{query_string}"
        else:
            initial_message = f"receive!{query_string}"

        logger.info(f"Sending initial message: {initial_message}")
        try:
            self.interface.sendText(initial_message, self.dest, wantAck=True)
        except Exception as e:
            logger.error(f"Failed to send initial message: {e}")
            sys.exit(1)

    async def send_all_chunks(self, receiver: dict):
        """
        Reads file content, splits it into chunks, then sequentially sends each chunk.

        Args:
            receiver (dict): A JSON object containing receiver-specific parameters.
        """
        file_content = self.read_file()
        chunks = self.chunk_content(file_content)
        total_chunks = len(chunks)
        logger.info(f"Total chunks to send: {total_chunks}")

        # Send the initial message with the receiver JSON
        self.send_receiver_message(total_chunks, receiver)

        # Sleep for the specified start delay
        if self.start_delay > 0:
            logger.info(f"Sleeping for {self.start_delay} seconds before sending chunks...")
            self.termination_event.wait(self.start_delay)  # Wait with termination support

        total_failures = 0
        for i, chunk in enumerate(chunks, start=1):
            if self.termination_event.is_set():
                logger.info("Termination event detected. Stopping chunk sending.")
                break
            failures = await self.send_chunk(chunk, i, total_chunks)  # Use await here
            total_failures += failures
            self.termination_event.wait(self.sleep_delay)  # Wait with termination support

        logger.info("All chunks sent successfully.")
        return total_chunks, total_failures

    def send_message(self, message: str):
        """Send a single message."""
        try:
            if self.dest:  # Check if self.dest is not None or empty
                self.interface.sendText(message, self.dest, wantAck=True)
                logger.info(f"Message sent to {self.dest}: {message}")
            else:
                self.interface.sendText(message, wantAck=True)  # Omit the destination parameter
                logger.info(f"Message sent without a specific destination: {message}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            sys.exit(1)

# --------- Signal Handling for Sending ----------
def setup_signal_handlers(sender):
    def handler(sig, frame):
        logger.info(f"Signal {sig} detected. Closing connection...")
        sender.termination_event.set()  # Signal termination
        sender.close_connection()
        sys.exit(0)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

# --------- Main Routine ----------
def main():
    parser = argparse.ArgumentParser(
        description="Meshtastic Sender: Process an image or send a file via a persistent Meshtastic connection."
    )
    parser.add_argument("-mo", "--mode", choices=["image_transfer", "file_transfer", "message"], default="message",
                        help="Mode to run: 'image_transfer' to process and send an image, "
                             "'file_transfer' to send a file, 'message' to send a single message.")
    parser.add_argument("-m", "--message", type=str, help="Message to send (required for 'message' mode).")
    parser.add_argument("-he", "--header", type=str, default="nc",
                        help="Header template (use '#' as digit placeholders)")
    # Parameters for image processing:
    parser.add_argument("-q", "--quality", type=int, default=90,
                        help="JPEG quality factor for optimization")
    parser.add_argument("-re", "--resize", type=str, default="800x600",
                        help="Resize dimensions (e.g., 800x600)")
    parser.add_argument("-o", "--output", type=str, default="base64_image.gz",
                        help="Output file from image processing")
    parser.add_argument("-cl", "--cleanup", action="store_true",
                        help="Enable cleanup of intermediate files after processing (default: off)")
    parser.add_argument("-p", "--preview_image", action="store_true",
                        help="Generate an ASCII preview of the image using jp2a (default: off)")
    # Upload parameters (only required if --upload is set)
    parser.add_argument("-rt", "--remote_target", type=str,
                        help="Remote path for file upload (required if --upload is set)")
    parser.add_argument("-k", "--ssh_key", type=str,
                        help="SSH identity file for rsync (required if --upload is set)")
    parser.add_argument("-u", "--upload", action="store_true",
                        help="Upload the processed image file using rsync (requires --remote_target and --ssh_key)")
    # Parameters for sending pipeline:
    parser.add_argument("-fp", "--file_path", type=str,
                        help="Path to text file to send (required for 'file_transfer' mode)")
    parser.add_argument("-cs", "--chunk_size", type=int, default=180,
                        help="Maximum length of each chunk when sending")
    parser.add_argument("-de", "--dest", type=str, default="!47a78d36",
                        help="Destination Node ID for Meshtastic send (default: '!47a78d36')")
    parser.add_argument("-mr", "--max_retries", type=int, default=10,
                        help="Maximum number of retries per chunk")
    parser.add_argument("-rd", "--retry_delay", type=int, default=1.0,
                        help="Delay in seconds between retries")
    parser.add_argument("-sld", "--sleep_delay", type=float, default=0.1,
                        help="Sleep delay in seconds between sending chunks")
    parser.add_argument("-std", "--start_delay", type=float, default=30.0,
                        help="Delay in seconds after sending the initial receiver message but before sending chunks")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug mode for detailed logging")
    parser.add_argument("-c", "--connection", type=str, choices=["tcp", "serial"], default="tcp",
                        help="Connection mode: 'tcp' or 'serial'")
    parser.add_argument("-t", "--tcp_host", type=str, default="localhost",
                        help="TCP host (default: localhost, used only in TCP mode)")
    parser.add_argument("-rp", "--receiver", type=str, default='{"sender": "eb314389"}',
                        help="Receiver JSON object containing receiver-specific parameters")
    args = parser.parse_args()

    # If upload is enabled, check that remote_target and ssh_key are provided.
    if args.upload:
        if not args.remote_target or not args.ssh_key:
            parser.error("--remote_target and --ssh_key are required when --upload is set.")

    configure_logging(args.debug)

    # Display Sender Parameters in an ASCII Table
    param_items = [
        ("Mode", args.mode),
        ("Header", args.header),
        ("Quality", args.quality),
        ("Resize", args.resize),
        ("ASCII Preview", args.preview_image),
        ("Output", args.output),
        ("File Path", args.file_path if args.file_path else args.output),
        ("Chunk Size", args.chunk_size),
        ("Destination", args.dest),
        ("Connection", args.connection),
        ("TCP Host", args.tcp_host if args.connection == "tcp" else "N/A"),
        ("Max Retries", args.max_retries),
        ("Retry Delay", args.retry_delay),
        ("Sleep Delay", args.sleep_delay),
        ("Start Delay", args.start_delay),
        ("Upload", args.upload),
        ("Remote Target", args.remote_target if args.remote_target else "N/A"),
        ("SSH Key", args.ssh_key if args.ssh_key else "N/A"),
        ("Receiver", args.receiver)
    ]
    print_table("Sender Parameters", param_items)

    # Initialize variables for execution summary
    total_chunks = 0
    total_failures = 0
    end_time = None

    try:
        asyncio.run(run_sender(args))
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        sys.exit(1)

async def run_sender(args):
    try:
        receiver = json.loads(args.receiver)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON for --receiver: {e}")
        sys.exit(1)

    start_time = time.time()

    if args.mode in ["image_transfer", "file_transfer"]:
        if args.mode == "image_transfer":
            print("Running image processing pipeline...")
            summary = optimize_compress_zip_base64encode_jpg(
                quality=args.quality,
                resize=args.resize,
                snapshot_url="http://localhost:8080/0/action/snapshot",
                output_file=args.output,
                cleanup=args.cleanup,
                preview_image=args.preview_image
            )
            if args.upload:
                print("Uploading processed image file...")
                upload_file(args.output, args.remote_target, args.ssh_key)
            if not args.file_path:
                args.file_path = args.output
            file_path = Path(args.file_path)
            with PersistentMeshtasticSender(
                file_path=file_path,
                chunk_size=args.chunk_size,
                dest=args.dest,
                connection=args.connection,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                header_template=args.header,
                sleep_delay=args.sleep_delay,
                start_delay=args.start_delay
            ) as sender:
                setup_signal_handlers(sender)
                try:
                    total_chunks, total_failures = await sender.send_all_chunks(receiver=receiver)
                finally:
                    sender.close_connection()
                    logger.info("Connection closed successfully.")
            end_time = time.time()

        elif args.mode == "file_transfer":
            if not args.file_path:
                logger.error("For file_transfer mode, --file_path is required.")
                sys.exit(1)

            print("Running file processing pipeline...")
            compressed_file = "compressed_file.gz"
            print(f"Compressing file using Zopfli gzip ...")
            with open(args.file_path, "rb") as f_in:
                data = f_in.read()
            compressed_data = zopfli.gzip.compress(data)
            with open(compressed_file, "wb") as f_out:
                f_out.write(compressed_data)

            zipped_size = os.stat(compressed_file).st_size
            print(f"Size after compression: {zipped_size} bytes")

            print("Encoding compressed file to Base64 ...")
            base64_encoded_file = "base64_encoded_file.gz"
            with open(compressed_file, "rb") as f_in:
                zipped_content = f_in.read()
            base64_encoded = base64.b64encode(zipped_content)
            with open(base64_encoded_file, "wb") as f_out:
                f_out.write(base64_encoded)

            base64_size = os.stat(base64_encoded_file).st_size
            print(f"Size after Base64 encoding: {base64_size} bytes")

            if args.upload:
                print("Uploading processed file...")
                upload_file(base64_encoded_file, args.remote_target, args.ssh_key)

            file_path = Path(base64_encoded_file)
            with PersistentMeshtasticSender(
                file_path=file_path,
                chunk_size=args.chunk_size,
                dest=args.dest,
                connection=args.connection,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                header_template=args.header,
                sleep_delay=args.sleep_delay,
                start_delay=args.start_delay
            ) as sender:
                setup_signal_handlers(sender)
                try:
                    total_chunks, total_failures = await sender.send_all_chunks(receiver=receiver)
                finally:
                    sender.close_connection()
                    logger.info("Connection closed successfully.")
            end_time = time.time()

    elif args.mode == "message":
        if not args.message:
            logger.error("For message mode, --message is required.")
            sys.exit(1)

        print("Sending a single message...")
        with PersistentMeshtasticSender(
            file_path=None,
            chunk_size=0,
            dest=args.dest,
            connection=args.connection,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
            header_template=args.header,
            sleep_delay=args.sleep_delay,
            start_delay=args.start_delay
        ) as sender:
            setup_signal_handlers(sender)
            try:
                sender.send_message(args.message)
            finally:
                sender.close_connection()
                logger.info("Connection closed successfully.")
        end_time = time.time()

    # Calculate total size of data sent
    if args.mode in ["image_transfer", "file_transfer"]:
        total_size = total_chunks * args.chunk_size
    else:
        total_size = 0

    # Calculate transmission speed
    elapsed_seconds = end_time - start_time
    speed = total_size / elapsed_seconds if elapsed_seconds > 0 else 0

    exec_summary = [
        ("Start Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))),
        ("End Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))),
        ("Time Elapsed", time.strftime("%H:%M:%S", time.gmtime(elapsed_seconds))),
        ("Total Chunks Sent", total_chunks),
        ("Total Data Sent", f"{total_size} bytes"),
        ("Transmission Speed", f"{speed:.2f} bytes/second"),
        ("Receiver", args.receiver)
    ]
    print_table("Execution Summary", exec_summary)

    def cleanup():
        if sender.interface:
            logger.info("Cleaning up Meshtastic connection...")
            sender.close_connection()

    atexit.register(cleanup)

if __name__ == "__main__":
    main()
