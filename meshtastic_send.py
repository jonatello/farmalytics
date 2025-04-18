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
    This script reads the content of the specified text file, chunks it into strings with a maximum length specified by chunk_size, and executes the meshtastic command for each chunk. The meshtastic command sends each chunk as a text message to the specified channel index and destination if provided. Logging is used to record the processing of each chunk.
"""

import subprocess
import argparse
import logging

# Function to read the content of the file
def read_file(file_path):
    """
    Reads the content of the specified file.

    Args:
        file_path (str): Path to the text file.

    Returns:
        str: Content of the file as a single string.
    """
    with open(file_path, 'r') as file:
        return file.read()

# Function to chunk the content into strings with a maximum length specified by chunk_size
def chunk_content(content, chunk_size):
    """
    Splits the content into chunks of specified size.

    Args:
        content (str): The content to be chunked.
        chunk_size (int): Maximum length of each chunk.

    Returns:
        list: List of chunks with each chunk having a maximum length of chunk_size.
    """
    return [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]

# Function to execute the command for each chunk
def execute_command_for_chunks(chunks, ch_index, dest):
    """
    Executes the meshtastic command for each chunk.

    Args:
        chunks (list): List of content chunks.
        ch_index (int): Channel index for the meshtastic command.
        dest (str): Destination for the meshtastic command.
    """
    total_chunks = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        # Construct the command with the current chunk, channel index, and destination
        command = f'meshtastic --host --ack --sendtext "{chunk}"'
        if ch_index is not None:
            command += f' --ch-index {ch_index}'
        if dest is not None:
            command += f' --dest {dest}'
        # Execute the command using subprocess
        subprocess.run(command, shell=True)
        # Log the progress
        logging.info(f"Processed chunk {i} of {total_chunks}: {chunk[:50]}...")

# Set up argument parser
parser = argparse.ArgumentParser(description="Chunk file content and execute command for each chunk.")
# Add argument for the file path
parser.add_argument("file_path", help="Path to the text file")
# Add argument for the chunk size
parser.add_argument("--chunk_size", type=int, default=200, help="Maximum length of each chunk")
# Add optional argument for the channel index
parser.add_argument("--ch_index", type=int, help="Channel index for the meshtastic command")
# Add optional argument for the destination
parser.add_argument("--dest", type=str, help="Destination for the meshtastic command")
# Parse the arguments
args = parser.parse_args()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Read the content of the file
file_content = read_file(args.file_path)

# Chunk the content into strings with a maximum length specified by chunk_size
chunks = chunk_content(file_content, args.chunk_size)

# Execute the command for each chunk
execute_command_for_chunks(chunks, args.ch_index, args.dest)
