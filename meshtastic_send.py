#!/usr/bin/env python3
"""
Usage:
    python3 meshtastic_send.py file_path --chunk_size CHUNK_SIZE [--ch_index CH_INDEX] [--dest DEST] [--connection CONNECTION]

Arguments:
    file_path:    Path to the text file containing the content to be chunked.
    --chunk_size: Maximum length of each chunk.
    --ch_index:   (Optional) Channel index for the meshtastic command.
    --dest:       (Optional) Destination for the meshtastic command.
    --connection: (Optional) Connection mode, either 'tcp' or 'serial' (default: tcp).

Examples:
    python3 meshtastic_send.py combined_message.log --chunk_size 200 --ch_index 6 --dest 12345 --connection tcp
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --connection serial

Description:
    This script reads the content of the specified text file, splits it into smaller chunks, and sends
    each chunk using a meshtastic command. It logs details of each send attempt and prints a summary at
    the end including timings, total chunks sent (and attempted retries), plus file sizes.
"""

import subprocess  # To run external commands
import argparse    # For command-line argument handling
import logging     # For logging messages
import time        # For timing and delays
import os          # For interacting with the filesystem (e.g., file sizes)
import base64      # For encoding file content to base64
import sys         # For exiting gracefully

# ---------------------- Utility Functions ----------------------

def read_file(file_path):
    """
    Reads the entire content from the specified file.

    Parameters:
        file_path (str): Path to the text file.

    Returns:
        str: File content.
    """
    try:
        with open(file_path, 'r') as file:
            return file.read()
    except Exception as e:
        logger.error(f"Error reading file '{file_path}': {e}")
        sys.exit(1)

def chunk_content(content, chunk_size):
    """
    Splits content into a list of substrings (chunks).

    Parameters:
        content (str): The full content string.
        chunk_size (int): Maximum length of each chunk.

    Returns:
        list: List of chunks.
    """
    return [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

def execute_command_for_chunks(chunks, ch_index, dest, connection_mode):
    """
    Sends each chunk using the meshtastic command. On failure, it retries up to a maximum count with exponential backoff.

    Parameters:
        chunks (list): List of content chunks.
        ch_index (int|None): Channel index option.
        dest (str|None): Destination option.
        connection_mode (str): Either 'tcp' or 'serial'.

    Returns:
        tuple: (total_chunks, failure_count)
               total_chunks: Number of chunks processed.
               failure_count: Total number of retry attempts encountered.
    """
    total_chunks = len(chunks)
    failure_count = 0
    max_retries = 10

    for i, chunk in enumerate(chunks, start=1):
        # Build the command.
        command = ['meshtastic']
        if connection_mode == 'tcp':
            command.append('--host')
        elif connection_mode == 'serial':
            command.append('--serial')
        command.extend(['--ack', '--sendtext', chunk])
        if ch_index is not None:
            command.extend(['--ch-index', str(ch_index)])
        if dest is not None:
            command.extend(['--dest', dest])

        retries = 0
        while retries < max_retries:
            try:
                subprocess.run(command, check=True, capture_output=True, text=True)
                logger.info(f"Successfully sent chunk {i}/{total_chunks}: {chunk[:50]}...")
                break  # Success: exit retry loop.
            except subprocess.CalledProcessError as e:
                retries += 1
                failure_count += 1
                detailed_error = (
                    f"Full command: {' '.join(command)}; "
                    f"Exit code: {e.returncode}; "
                    f"STDOUT: {e.stdout.strip() if e.stdout else 'None'}; "
                    f"STDERR: {e.stderr.strip() if e.stderr else 'None'}"
                )
                logger.warning(f"Retry {retries}/{max_retries} for chunk {i}/{total_chunks} returned exit status {e.returncode}. Details: {detailed_error}")
                time.sleep(2 ** retries)  # Exponential backoff.
                if retries == max_retries:
                    logger.error(f"Aborting after {max_retries} retries for chunk {i}.")
                    sys.exit(1)
    logger.info(f"Total failures/retries: {failure_count}")
    return total_chunks, failure_count

# ---------------------- Command-Line Argument Parsing ----------------------

parser = argparse.ArgumentParser(description="Chunk file content and send via meshtastic.")
parser.add_argument("file_path", help="Path to the text file")
parser.add_argument("--chunk_size", type=int, default=200, help="Maximum length of each chunk")
parser.add_argument("--ch_index", type=int, help="Channel index for the meshtastic command")
parser.add_argument("--dest", type=str, help="Destination for the meshtastic command")
parser.add_argument("--connection", type=str, choices=['tcp', 'serial'], default='tcp', help="Connection mode: 'tcp' or 'serial'")
args = parser.parse_args()

# ---------------------- Logging Configuration ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# Add a file handler for DEBUG-level messages.
file_handler = logging.FileHandler("debug_messages.log")
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
file_handler.setLevel(logging.DEBUG)
logger.addHandler(file_handler)

# ---------------------- Main Execution Flow ----------------------
start_time = time.time()

# Read the file, and calculate sizes.
file_content = read_file(args.file_path)
file_size = os.path.getsize(args.file_path)
base64_content = base64.b64encode(file_content.encode('utf-8'))
base64_size = len(base64_content)

# Split file content into chunks.
chunks = chunk_content(file_content, args.chunk_size)

# Process chunks using the meshtastic command.
total_chunks, failure_count = execute_command_for_chunks(chunks, args.ch_index, args.dest, args.connection)

end_time = time.time()
elapsed_seconds = end_time - start_time
formatted_elapsed = time.strftime("%H:%M:%S", time.gmtime(elapsed_seconds))
total_attempts = total_chunks + failure_count

# Prepare and present the summary.
summary_lines = [
    "----- Execution Summary -----",
    f"Start Time:          {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}",
    f"End Time:            {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}",
    f"Time Elapsed:        {formatted_elapsed} (HH:MM:SS)",
    f"Total Chunks Sent:   {total_chunks}",
    f"Total Attempts:      {total_attempts} (includes {failure_count} retries)",
    f"Initial File Size:   {file_size} bytes",
    f"Base64 File Size:    {base64_size} bytes",
    "------------------------------"
]

for line in summary_lines:
    logger.info(line)
    print(line)
