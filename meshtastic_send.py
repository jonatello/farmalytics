#!/usr/bin/env python3
"""
Usage:
    python meshtastic_send.py file_path --ch_index CH_INDEX

Arguments:
    file_path: Path to the text file containing the content to be chunked.
    --ch_index: Channel index for the meshtastic command.

Examples:
    python meshtastic_send.py combined_message.log --ch_index 6
    python meshtastic_send.py combined_message.log --ch_index 3

Description:
    This script reads the content of the specified text file, chunks it into strings with a maximum length of 200 characters, and executes the meshtastic command for each chunk. The meshtastic command sends each chunk as a text message to the specified channel index. Logging is used to record the processing of each chunk.
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

# Function to chunk the content into strings with a maximum length of 200 characters
def chunk_content(content, chunk_size=200):
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
def execute_command_for_chunks(chunks, ch_index):
    """
    Executes the meshtastic command for each chunk.

    Args:
        chunks (list): List of content chunks.
        ch_index (int): Channel index for the meshtastic command.
    """
    for chunk in chunks:
        # Construct the command with the current chunk and channel index
        command = f'meshtastic --host --ch-index {ch_index} --ack --sendtext "{chunk}"'
        # Execute the command using subprocess
        subprocess.run(command, shell=True)
        # Log the progress
        logging.info(f"Processed chunk: {chunk[:50]}...")

# Set up argument parser
parser = argparse.ArgumentParser(description="Chunk file content and execute command for each chunk.")
# Add argument for the file path
parser.add_argument("file_path", help="Path to the text file")
# Add argument for the channel index
parser.add_argument("--ch_index", type=int, required=True, help="Channel index for the meshtastic command")
# Parse the arguments
args = parser.parse_args()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Read the content of the file
file_content = read_file(args.file_path)

# Chunk the content into strings with a maximum length of 200 characters
chunks = chunk_content(file_content)

# Execute the command for each chunk
execute_command_for_chunks(chunks, args.ch_index)
