#!/usr/bin/env python3
"""
Meshtastic Sender

This script combines two pipelines:
  1. Image Processing Pipeline:
     - Triggers a snapshot capture via a configured snapshot URL.
     - Copies the snapshot from /var/lib/motion/lastsnap.jpg into the current directory.
     - Optimizes the JPEG using jpegoptim and jpegtran, then resizes via ImageMagick’s convert.
     - Compresses the image with Zopfli gzip and Base64 encodes the result.
     - Writes the Base64 output to a file.
     
  2. Persistent Sending Pipeline:
     - Reads content from a specified file.
     - Splits the content into fixed-size chunks.
     - Optionally prepends a header (generated from a template) to each chunk.
     - Uses a persistent Meshtastic connection (TCP or serial) to send each chunk sequentially,
       with retries and inter-chunk delays.
       
If no mode is specified, the script defaults to “all”—that is, it will run both pipelines in sequence.
When in “all” or “process” mode with the upload flag set, the processed image file is uploaded via rsync.

### Parameters:
  - `--mode`: Specifies the mode of operation (`process`, `send`, or `all`).
  - `--header`: Template for prepending headers to chunks (use `#` as digit placeholders).
  - `--quality`: JPEG quality factor for optimization (default: 75).
  - `--resize`: Resize dimensions for the image (e.g., `800x600`).
  - `--output`: Output file for the processed image (default: `base64_image.gz`).
  - `--cleanup`: Enables cleanup of intermediate files after processing.
  - `--remote_target`: Remote path for file upload (required if `--upload` is set).
  - `--ssh_key`: SSH identity file for rsync (required if `--upload` is set).
  - `--upload`: Enables uploading of the processed image file using rsync.
  - `--file_path`: Path to the file to send (defaults to the output file if not provided).
  - `--chunk_size`: Maximum length of each chunk when sending (default: 200).
  - `--ch_index`: Starting chunk index (default: 1).
  - `--dest`: Destination token for Meshtastic send (default: `!47a78d36`).
  - `--ack`: Enables acknowledgment mode for sending.
  - `--max_retries`: Maximum number of retries per chunk (default: 10).
  - `--retry_delay`: Delay in seconds between retries (default: 1).
  - `--sleep_delay`: Sleep delay in seconds between sending chunks (default: 1.0).
  - `--start_delay`: Delay in seconds after sending the initial message but before sending chunks (default: 0.0).
  - `--connection`: Connection mode (`tcp` or `serial`, default: `tcp`).
  - `--tcp_host`: TCP host for Meshtastic connection (default: `localhost`).
  - `--debug`: Enables debug mode for detailed logging.

### Updated Usage Examples:
  --- To process an image and then upload and send it ---
  python3 meshtastic_sender.py --mode all --header nc --upload \
    --quality 75 --resize 800x600 --remote_target "user@host:/remote/path" --ssh_key "/path/to/id_rsa" \
    --chunk_size 180 --dest '!47a78d36' --connection tcp --tcp_host 192.168.1.100 --ack --sleep_delay 1

  --- To run only the image processing pipeline and optionally upload ---
  python3 meshtastic_sender.py --mode process --quality 75 --resize 800x600 \
    --upload --remote_target "user@host:/remote/path" --ssh_key "/path/to/id_rsa"

  --- To send an already-processed file ---
  python3 meshtastic_sender.py --mode send --file_path base64_image.gz \
    --chunk_size 180 --dest '!47a78d36' --connection serial --ack --sleep_delay 1

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
        quality=75,
        resize="800x600",
        snapshot_url="http://localhost:8080/0/action/snapshot",
        output_file="base64_image.gz",
        cleanup=False):
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
    summary['Initial Size'] = f"{initial_size} bytes"
    
    print(f"Optimizing JPEG with quality {quality} ...")
    subprocess.run(["jpegoptim", f"--max={quality}", "--strip-all", image_path], check=True)
    
    subprocess.run(["jpegtran", "-optimize", "-progressive", "-copy", "none",
                    "-outfile", compressed_image_path, image_path], check=True)
    optimized_size = os.stat(compressed_image_path).st_size
    print(f"Size after optimization: {optimized_size} bytes")
    summary['Optimized Size'] = f"{optimized_size} bytes"
    
    print(f"Resizing image to {resize} ...")
    subprocess.run(["convert", compressed_image_path, "-resize", resize, compressed_image_path], check=True)
    resized_size = os.stat(compressed_image_path).st_size
    print(f"Size after resizing: {resized_size} bytes")
    summary['Resized Size'] = f"{resized_size} bytes"
    
    print("Compressing image using Zopfli gzip ...")
    with open(compressed_image_path, "rb") as f_in:
        data = f_in.read()
    compressed_data = zopfli.gzip.compress(data)
    with open(zipped_image_path, "wb") as f_out:
        f_out.write(compressed_data)
    zipped_size = os.stat(zipped_image_path).st_size
    print(f"Size after compression: {zipped_size} bytes")
    summary['Compressed Size'] = f"{zipped_size} bytes"
    
    print("Encoding compressed image to Base64 ...")
    with open(zipped_image_path, "rb") as f_in:
        zipped_content = f_in.read()
    base64_encoded = base64.b64encode(zipped_content)
    with open(output_file, "wb") as f_out:
        f_out.write(base64_encoded)
    base64_size = os.stat(output_file).st_size
    print(f"Size after Base64 encoding: {base64_size} bytes")
    summary['Base64 Size'] = f"{base64_size} bytes"
    
    total_chars = len(base64_encoded)
    print(f"Total characters in Base64 data: {total_chars}")
    summary['Total Characters'] = total_chars
    
    os.remove(image_path)
    os.remove(compressed_image_path)
    os.remove(zipped_image_path)
    
    print("Image processing complete. Base64 output saved to:", output_file)
    return summary

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

DEFAULT_MAX_RETRIES = 10
DEFAULT_RETRY_DELAY = 1      # seconds
DEFAULT_SLEEP_DELAY = 1.0    # seconds

class PersistentMeshtasticSender:
    """
    Uses a persistent Meshtastic connection to send file content.

    This class reads a file, splits it into chunks, and sends each chunk sequentially.
    An optional header (derived from a template) can be prepended to each chunk.
    Includes retry logic and a delay between sends.
    """
    def __init__(self, file_path: Path, chunk_size: int, ch_index: int, dest: str,
                 connection: str, max_retries: int = DEFAULT_MAX_RETRIES,
                 retry_delay: int = DEFAULT_RETRY_DELAY, header_template: str = None,
                 use_ack: bool = False, sleep_delay: float = DEFAULT_SLEEP_DELAY,
                 start_delay: float = 0.0):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.ch_index = ch_index
        self.dest = dest
        self.connection = connection.lower()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.header_template = header_template
        self.use_ack = use_ack
        self.sleep_delay = sleep_delay
        self.start_delay = start_delay
        self.interface = None

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
        if self.connection == 'tcp':
            logger.info("Establishing persistent TCP connection...")
            try:
                self.interface = TCPInterface(hostname=tcp_host)
            except Exception as e:
                logger.error(f"Error establishing TCP connection: {e}")
                sys.exit(1)
        elif self.connection == 'serial':
            logger.info("Establishing persistent Serial connection...")
            try:
                self.interface = SerialInterface()
            except Exception as e:
                logger.error(f"Error establishing Serial connection: {e}")
                sys.exit(1)
        else:
            logger.error(f"Unknown connection type: {self.connection}")
            sys.exit(1)
        logger.info("Persistent connection established.")

    def close_connection(self):
        """Closes the persistent Meshtastic connection."""
        try:
            self.interface.close()
            logger.info("Persistent connection closed.")
        except Exception as e:
            logger.error(f"Error closing connection: {e}")

    def send_chunk(self, message: str, chunk_index: int, total_chunks: int) -> int:
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
                self.interface.sendText(full_message, wantAck=self.use_ack)
                remaining = total_chunks - chunk_index
                logger.info(f"Sent chunk {chunk_index}/{total_chunks} with header '{header}' "
                            f"(Attempt {attempt+1}/{self.max_retries}, {remaining} remaining)")
                return attempt
            except Exception as e:
                attempt += 1
                logger.warning(f"Retry {attempt}/{self.max_retries} for chunk {chunk_index} due to error: {e}")
                time.sleep(self.retry_delay)
                if attempt == self.max_retries:
                    logger.error(f"Aborting after {self.max_retries} retries for chunk {chunk_index}.")
                    sys.exit(1)
        return attempt

    def send_initial_message(self, total_chunks: int):
        """
        Sends an initial message with the header "messagecount!" followed by the maximum header value.
        """
        if self.header_template:
            max_header = self.generate_header(total_chunks, total_chunks)
            initial_message = f"messagecount!{max_header}"
        else:
            initial_message = f"messagecount!{total_chunks}"

        logger.info(f"Sending initial message: {initial_message}")
        try:
            self.interface.sendText(initial_message, wantAck=self.use_ack)
        except Exception as e:
            logger.error(f"Failed to send initial message: {e}")
            sys.exit(1)

    def send_all_chunks(self):
        """Reads file content, splits it into chunks, then sequentially sends each chunk."""
        file_content = self.read_file()
        chunks = self.chunk_content(file_content)
        total_chunks = len(chunks)
        logger.info(f"Total chunks to send: {total_chunks}")

        # Send the initial message with the maximum header value
        self.send_initial_message(total_chunks)

        # Sleep for the specified start delay
        if self.start_delay > 0:
            logger.info(f"Sleeping for {self.start_delay} seconds before sending chunks...")
            time.sleep(self.start_delay)

        total_failures = 0
        for i, chunk in enumerate(chunks, start=1):
            failures = self.send_chunk(chunk, i, total_chunks)
            total_failures += failures
            time.sleep(self.sleep_delay)
        return total_chunks, total_failures

# --------- Signal Handling for Sending ----------
def setup_signal_handlers(sender):
    def handler(sig, frame):
        logger.info("CTRL+C detected. Closing connection...")
        sender.close_connection()
        sys.exit(0)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

# --------- Main Routine ----------
def main():
    parser = argparse.ArgumentParser(
        description="Meshtastic Sender: Process an image and/or send file content via a persistent Meshtastic connection."
    )
    parser.add_argument("--mode", choices=["send", "process", "all"],
                        default="all",
                        help="Mode to run: 'process' to process an image, 'send' to send file content, "
                             "'all' to run both (default: all)")
    parser.add_argument("--header", type=str, default="pn",
                        help="Header template (use '#' as digit placeholders)")
    # Parameters for image processing:
    parser.add_argument("--quality", type=int, default=75,
                        help="JPEG quality factor for optimization")
    parser.add_argument("--resize", type=str, default="800x600",
                        help="Resize dimensions (e.g., 800x600)")
    parser.add_argument("--output", type=str, default="base64_image.gz",
                        help="Output file from image processing")
    parser.add_argument("--cleanup", action="store_true",
                        help="Enable cleanup of intermediate files after processing (default: off)")
    # Upload parameters (only required if --upload is set)
    parser.add_argument("--remote_target", type=str,
                        help="Remote path for file upload (required if --upload is set)")
    parser.add_argument("--ssh_key", type=str,
                        help="SSH identity file for rsync (required if --upload is set)")
    parser.add_argument("--upload", action="store_true",
                        help="Upload the processed image file using rsync (requires --remote_target and --ssh_key)")
    # Parameters for sending pipeline:
    parser.add_argument("--file_path", type=str,
                        help="Path to text file to send (if not provided in 'all' mode, defaults to the output file)")
    parser.add_argument("--chunk_size", type=int, default=200,
                        help="Maximum length of each chunk when sending")
    parser.add_argument("--ch_index", type=int, default=1,
                        help="Starting chunk index (default: 1)")
    parser.add_argument("--dest", type=str, default="!47a78d36",
                        help="Destination token for Meshtastic send")
    parser.add_argument("--ack", action="store_true",
                        help="Enable ACK mode for sending")
    parser.add_argument("--max_retries", type=int, default=DEFAULT_MAX_RETRIES,
                        help="Maximum number of retries per chunk")
    parser.add_argument("--retry_delay", type=int, default=DEFAULT_RETRY_DELAY,
                        help="Delay in seconds between retries")
    parser.add_argument("--sleep_delay", type=float, default=DEFAULT_SLEEP_DELAY,
                        help="Sleep delay in seconds between sending chunks")
    parser.add_argument("--start_delay", type=float, default=0.0,
                        help="Delay in seconds after sending the initial message but before sending chunks")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode for detailed logging")
    parser.add_argument("--connection", type=str, choices=["tcp", "serial"], default="tcp",
                        help="Connection mode: 'tcp' or 'serial'")
    parser.add_argument("--tcp_host", type=str, default="localhost",
                        help="TCP host (default: localhost, used only in TCP mode)")
    args = parser.parse_args()

    # If upload is enabled, check that remote_target and ssh_key are provided.
    if args.upload:
        if not args.remote_target or not args.ssh_key:
            parser.error("--remote_target and --ssh_key are required when --upload is set.")

    configure_logging(args.debug)

    # --------- Display Sender Parameters in an ASCII Table ---------
    param_items = [
        ("Mode", args.mode),
        ("Header", args.header),
        ("Quality", args.quality),
        ("Resize", args.resize),
        ("Output", args.output),
        ("File Path", args.file_path if args.file_path else args.output),
        ("Chunk Size", args.chunk_size),
        ("Destination", args.dest),
        ("Connection", args.connection),
        ("TCP Host", args.tcp_host if args.connection == "tcp" else "N/A"),
        ("ACK Mode", args.ack),
        ("Max Retries", args.max_retries),
        ("Retry Delay", args.retry_delay),
        ("Sleep Delay", args.sleep_delay),
        ("Start Delay", args.start_delay),
        ("Upload", args.upload),
        ("Remote Target", args.remote_target if args.remote_target else "N/A"),
        ("SSH Key", args.ssh_key if args.ssh_key else "N/A")
    ]
    print_table("Sender Parameters", param_items)

    if args.mode == "process":
        print("Running image processing pipeline...")
        summary = optimize_compress_zip_base64encode_jpg(
            quality=args.quality,
            resize=args.resize,
            snapshot_url="http://localhost:8080/0/action/snapshot",
            output_file=args.output,
            cleanup=args.cleanup
        )
        print("Image processing complete. Summary:")
        for k, v in summary.items():
            print(f"{k}: {v}")
        if args.upload:
            print("Uploading processed image file...")
            upload_file(args.output, args.remote_target, args.ssh_key)
    elif args.mode == "send":
        if not args.file_path:
            logger.error("For send mode, --file_path is required.")
            sys.exit(1)
        file_path = Path(args.file_path)
        sender = PersistentMeshtasticSender(
            file_path=file_path,
            chunk_size=args.chunk_size,
            ch_index=args.ch_index,
            dest=args.dest,
            connection=args.connection,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
            header_template=args.header,
            use_ack=args.ack,
            sleep_delay=args.sleep_delay,
            start_delay=args.start_delay
        )
        setup_signal_handlers(sender)
        start_time = time.time()
        sender.open_connection(tcp_host=args.tcp_host)  # Pass tcp_host to open_connection
        total_chunks, total_failures = sender.send_all_chunks()
        sender.close_connection()
        end_time = time.time()
        elapsed_seconds = end_time - start_time
        file_size = sender.get_file_size()
        formatted_elapsed = time.strftime("%H:%M:%S", time.gmtime(elapsed_seconds))
        total_attempts = total_chunks + total_failures
        speed = file_size / elapsed_seconds if elapsed_seconds > 0 else file_size
        
        exec_summary = [
            ("Start Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))),
            ("End Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))),
            ("Time Elapsed", formatted_elapsed),
            ("Total Chunks Sent", total_chunks),
            ("Total Attempts", f"{total_attempts} (includes {total_failures} retries)"),
            ("Initial File Size", f"{file_size} bytes"),
            ("Transmission Speed", f"{speed:.2f} bytes/second")
        ]
        print_table("Execution Summary", exec_summary)
    else:  # Mode "all": Run both pipelines in sequence.
        print("Running image processing pipeline...")
        summary = optimize_compress_zip_base64encode_jpg(
            quality=args.quality,
            resize=args.resize,
            snapshot_url="http://localhost:8080/0/action/snapshot",
            output_file=args.output,
            cleanup=args.cleanup
        )
        print("Image processing complete. Summary:")
        for k, v in summary.items():
            print(f"{k}: {v}")
        if args.upload:
            print("Uploading processed image file...")
            upload_file(args.output, args.remote_target, args.ssh_key)
        # Default file_path to the processing output if not provided.
        if not args.file_path:
            args.file_path = args.output
        file_path = Path(args.file_path)
        sender = PersistentMeshtasticSender(
            file_path=file_path,
            chunk_size=args.chunk_size,
            ch_index=args.ch_index,
            dest=args.dest,
            connection=args.connection,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
            header_template=args.header,
            use_ack=args.ack,
            sleep_delay=args.sleep_delay
        )
        setup_signal_handlers(sender)
        start_time = time.time()
        sender.open_connection(tcp_host=args.tcp_host)  # Pass tcp_host to open_connection
        total_chunks, total_failures = sender.send_all_chunks()
        sender.close_connection()
        end_time = time.time()
        elapsed_seconds = end_time - start_time
        file_size = sender.get_file_size()
        formatted_elapsed = time.strftime("%H:%M:%S", time.gmtime(elapsed_seconds))
        total_attempts = total_chunks + total_failures
        speed = file_size / elapsed_seconds if elapsed_seconds > 0 else file_size
        
        exec_summary = [
            ("Start Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))),
            ("End Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))),
            ("Time Elapsed", formatted_elapsed),
            ("Total Chunks Sent", total_chunks),
            ("Total Attempts", f"{total_attempts} (includes {total_failures} retries)"),
            ("Initial File Size", f"{file_size} bytes"),
            ("Transmission Speed", f"{speed:.2f} bytes/second")
        ]
        print_table("Execution Summary", exec_summary)

if __name__ == "__main__":
    main()
