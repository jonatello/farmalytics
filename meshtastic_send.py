#!/usr/bin/env python3
"""
Usage:
    python meshtastic_send.py file_path --chunk_size CHUNK_SIZE [--ch_index CH_INDEX] [--dest DEST]

Arguments:
    file_path: Path to the text file containing the content to be chunked.
    --chunk_size: Maximum length of each chunk.
    --ch_index: (Optional) Channel index for the meshtastic command.
    --dest: (Optional) Destination for the meshtastic command.

Examples:
    python meshtastic_send.py combined_message.log --chunk_size 200 --ch_index 6 --dest 12345
    python meshtastic_send.py combined_message.log --chunk_size 150

Description:
    This script reads the content of the specified text file, splits it into smaller chunks, and sends
    each chunk using a meshtastic command. It logs details of each action and, at the end, prints
    a summary including start and end times, elapsed time, total chunks sent (and retried), plus file sizes.
"""

import subprocess      # To run external commands
import argparse        # To handle command-line arguments
import logging         # For logging messages
import time            # To keep track of time and delays
import os              # To interact with the operating system (e.g., file sizes)
import base64          # To encode the file content to base64

# ---------------------- Utility Functions ----------------------

def read_file(file_path):
    """
    Reads the content from the specified file.

    Parameters:
        file_path (str): The path to the text file.

    Returns:
        str: The entire file content as a string.
    """
    with open(file_path, 'r') as file:
        return file.read()

def chunk_content(content, chunk_size):
    """
    Splits a large string into a list of smaller strings (chunks).

    Parameters:
        content (str): The content to be split.
        chunk_size (int): The maximum length of each chunk.
    
    Returns:
        list: A list of chunks.
    """
    return [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

def execute_command_for_chunks(chunks, ch_index, dest):
    """
    Sends each chunk using the meshtastic command. If sending fails, it retries up to a maximum count.
    
    Parameters:
        chunks (list): List of content chunks.
        ch_index (int): Optional channel index.
        dest (str): Optional destination.
    
    Returns:
        tuple: (total_chunks, failure_count)
               total_chunks: Number of chunks processed.
               failure_count: The total number of retry attempts recorded.
    """
    total_chunks = len(chunks)    # Count how many chunks we have to send
    failure_count = 0             # Counter to track the number of retry attempts (failures)

    # Process each chunk one by one
    for i, chunk in enumerate(chunks, start=1):
        # Build the command string with the current chunk.
        command = f'meshtastic --host --ack --sendtext "{chunk}"'
        if ch_index is not None:
            command += f' --ch-index {ch_index}'
        if dest is not None:
            command += f' --dest {dest}'
        
        retries = 0          # Counter for the number of attempts on this chunk
        max_retries = 10     # Maximum retries allowed per chunk

        # Retry mechanism: try sending the chunk until successful, or exit after too many retries.
        while retries < max_retries:
            try:
                # Run the command. If it fails, an exception will be thrown.
                subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
                # Log a success message with a timestamp to both the console and file.
                logger.info(f"Successfully sent chunk {i} of {total_chunks}: {chunk[:50]}...")
                break  # Exit the retry loop if the command was successful.
            except subprocess.CalledProcessError as e:
                retries += 1
                failure_count += 1
                # Log a warning message if the command fails.
                logger.warning(f"Retry {retries}/{max_retries} for chunk {i} due to error: {e}")
                time.sleep(1)  # Pause for 1 second before retrying.
                if retries == max_retries:
                    logger.error(f"Aborting after {max_retries} retries for chunk {i}.")
                    exit(1)  # Exit the entire script if retries exceed the allowed limit.
    
    # Log the total number of retry failures after processing all chunks.
    logger.info(f"Total failures/retries: {failure_count}")
    return total_chunks, failure_count

# ---------------------- Command-Line Argument Parsing ----------------------

# Create a parser for command-line arguments and define expected parameters.
parser = argparse.ArgumentParser(description="Chunk file content and execute command for each chunk.")
parser.add_argument("file_path", help="Path to the text file")
parser.add_argument("--chunk_size", type=int, default=200, help="Maximum length of each chunk")
parser.add_argument("--ch_index", type=int, help="Channel index for the meshtastic command")
parser.add_argument("--dest", type=str, help="Destination for the meshtastic command")
args = parser.parse_args()

# ---------------------- Logging Configuration ----------------------

# Set up basic logging to the console with a timestamp and message level.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# Add a file handler so that all logs are also saved to 'debug_messages.log'.
file_handler = logging.FileHandler("debug_messages.log")
file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(file_formatter)
file_handler.setLevel(logging.DEBUG)  # Log all debug and above levels to the file.
logger.addHandler(file_handler)

# ---------------------- Main Execution Flow ----------------------

# Record the start time of the script
start_time = time.time()

# Read the file content from the given file path.
file_content = read_file(args.file_path)

# Get the initial file size in bytes.
file_size = os.path.getsize(args.file_path)

# Encode the file content to base64 to calculate its size when encoded.
base64_content = base64.b64encode(file_content.encode('utf-8'))
base64_size = len(base64_content)

# Split the file content into smaller chunks as specified.
chunks = chunk_content(file_content, args.chunk_size)

# Process each chunk: send it using the meshtastic command and record total chunks and retries.
total_chunks, failure_count = execute_command_for_chunks(chunks, args.ch_index, args.dest)

# Record the end time of the script.
end_time = time.time()

# Calculate how much time was spent executing the script.
elapsed_seconds = end_time - start_time
# Format the elapsed time in hours:minutes:seconds.
formatted_elapsed = time.strftime("%H:%M:%S", time.gmtime(elapsed_seconds))

# Calculate the total number of attempts (each chunk + each retry attempt).
total_attempts = total_chunks + failure_count

# Log a summary of the entire execution process.
logger.info("----- Execution Summary -----")
logger.info(f"Start Time:          {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")
logger.info(f"End Time:            {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
logger.info(f"Time Elapsed:        {formatted_elapsed} (HH:MM:SS)")
logger.info(f"Total Chunks Sent:   {total_chunks}")
logger.info(f"Total Attempts:      {total_attempts} (this includes {failure_count} retries)")
logger.info(f"Initial File Size:   {file_size} bytes")
logger.info(f"Base64 File Size:    {base64_size} bytes")
logger.info("------------------------------")
