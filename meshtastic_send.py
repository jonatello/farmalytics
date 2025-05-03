#!/usr/bin/env python3
"""
MeshtasticSend - Split and send file content via a persistent Meshtastic connection

Usage:
    python3 meshtastic_send.py file_path --chunk_size CHUNK_SIZE [--ch_index CH_INDEX]
       [--dest DEST] [--connection CONNECTION] [--header HEADER] [--ack]
       [--max_retries MAX_RETRIES] [--retry_delay RETRY_DELAY] [--sleep_delay SLEEP_DELAY]

Examples:
    python3 meshtastic_send.py combined_message.log --chunk_size 200 --ch_index 6 --dest '!47a78d36' --connection tcp
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --connection serial
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --header ab --connection tcp
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --ack --header ab --connection tcp
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --sleep_delay 1 --ack --header ab --connection tcp

Description:
    This script reads the content of the specified text file, splits it into chunks,
    and sends each chunk over a persistent Meshtastic connection.
    
    A persistent connection is established (using TCPInterface or SerialInterface)
    and used to send all messages—minimizing process overhead and speeding transmissions.
    
    If a header is supplied via --header, that header is prepended to each message.
    Without any '#' placeholders, the script computes the minimal digit width 
    based on the total number of chunks.
    
    By default, ACK mode is not used (i.e. sendText is called with wantAck=False).
    Use the --ack flag to enable ACK mode (i.e. call sendText with wantAck=True).
    
    In addition, a sleep delay between sending chunks is introduced. The delay defaults
    to 1 second and can be adjusted via the --sleep_delay parameter.
    
    Messages are sent sequentially over the persistent connection.
"""

import argparse
import base64
import logging
import sys
import time
from pathlib import Path
import re

# Import persistent connection interfaces from Meshtastic.
from meshtastic.tcp_interface import TCPInterface
from meshtastic.serial_interface import SerialInterface

# Constants for defaults.
DEFAULT_MAX_RETRIES = 10
DEFAULT_RETRY_DELAY = 1  # seconds between retries
DEFAULT_SLEEP_DELAY = 1.0  # seconds between sends

def setup_logging():
    logger = logging.getLogger("MeshtasticSender")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    
    # Console handler (INFO+)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (DEBUG)
    file_handler = logging.FileHandler("debug_messages.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

class PersistentMeshtasticSender:
    """
    Uses a persistent connection (TCP or Serial) to send data over Meshtastic.
    
    This class reads a file, splits it into chunks, and sends each chunk
    over a single established connection. It supports optional header generation,
    retries, and an arbitrary sleep delay between each send.
    
    By default, ACK mode is off (wantAck=False). When the --ack flag is provided,
    sendText is called with wantAck=True.
    """
    def __init__(self, file_path: Path, chunk_size: int, ch_index: int, dest: str,
                 connection: str, max_retries: int = DEFAULT_MAX_RETRIES,
                 retry_delay: int = DEFAULT_RETRY_DELAY, header_template: str = None,
                 use_ack: bool = False, sleep_delay: float = DEFAULT_SLEEP_DELAY):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.ch_index = ch_index
        self.dest = dest
        self.connection = connection.lower()  # 'tcp' or 'serial'
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.header_template = header_template
        self.use_ack = use_ack
        self.sleep_delay = sleep_delay

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
        """
        Generate a header for the given chunk index based on the header template.
        
        If no header_template is provided, returns an empty string.
        If the header_template contains '#' characters, those placeholders are used;
        otherwise, the minimal digit width (based on total_chunks) is used.
        The final header always ends with an exclamation mark.
        """
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

    def open_connection(self):
        """Establish a persistent connection using TCPInterface or SerialInterface."""
        if self.connection == 'tcp':
            logger.info("Establishing persistent TCP connection...")
            try:
                self.interface = TCPInterface(hostname="localhost")
            except Exception as e:
                logger.error(f"Error establishing TCP connection: {e}")
                sys.exit(1)
        elif self.connection == 'serial':
            logger.info("Establishing persistent Serial connection...")
            try:
                self.interface = SerialInterface()  # Adjust serial parameters if needed.
            except Exception as e:
                logger.error(f"Error establishing Serial connection: {e}")
                sys.exit(1)
        else:
            logger.error(f"Unknown connection type: {self.connection}")
            sys.exit(1)
        logger.info("Persistent connection established.")

    def close_connection(self):
        """Close the persistent connection."""
        try:
            self.interface.close()
            logger.info("Persistent connection closed.")
        except Exception as e:
            logger.error(f"Error closing connection: {e}")

    def send_chunk(self, message: str, chunk_index: int, total_chunks: int) -> int:
        """
        Send a single chunk with retries.
        
        If a header is provided, it is prepended to the message.
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
                # Pass the wantAck parameter based on our flag.
                self.interface.sendText(full_message, wantAck=self.use_ack)
                remaining = total_chunks - chunk_index
                logger.info(f"Successfully sent chunk {chunk_index}/{total_chunks} with header '{header}' "
                            f"(Attempt {attempt+1}/{self.max_retries}, {remaining} remaining chunks)")
                return attempt
            except Exception as e:
                attempt += 1
                logger.warning(f"Retry {attempt}/{self.max_retries} for chunk {chunk_index} due to error: {e}")
                time.sleep(self.retry_delay)
                if attempt == self.max_retries:
                    logger.error(f"Aborting after {self.max_retries} retries for chunk {chunk_index}.")
                    sys.exit(1)
        return attempt

    def send_all_chunks(self):
        """Reads file content, splits it into chunks, sends each chunk sequentially, with a delay between each send."""
        file_content = self.read_file()
        chunks = self.chunk_content(file_content)
        total_chunks = len(chunks)
        logger.info(f"Total chunks to send: {total_chunks}")
        total_failures = 0
        for i, chunk in enumerate(chunks, start=1):
            failures = self.send_chunk(chunk, i, total_chunks)
            total_failures += failures
            time.sleep(self.sleep_delay)
        return total_chunks, total_failures

def main():
    parser = argparse.ArgumentParser(description="Send file content via a persistent Meshtastic connection.")
    parser.add_argument("file_path", help="Path to the text file")
    parser.add_argument("--chunk_size", type=int, default=200, help="Maximum length of each chunk")
    parser.add_argument("--ch_index", type=int, help="Channel index for the Meshtastic command")
    parser.add_argument("--dest", type=str, help="Destination for the Meshtastic command")
    parser.add_argument("--connection", type=str, choices=['tcp', 'serial'], default='tcp',
                        help="Connection mode: 'tcp' or 'serial'")
    parser.add_argument("--header", type=str,
                        help="Header template to prepend to each message. Use '#' for digit placeholders. "
                             "If not specified, no header is prepended.")
    parser.add_argument("--ack", action="store_true",
                        help="Enable ACK mode (i.e. call sendText with wantAck=True)")
    parser.add_argument("--max_retries", type=int, default=DEFAULT_MAX_RETRIES,
                        help=f"Maximum number of retries per chunk (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--retry_delay", type=int, default=DEFAULT_RETRY_DELAY,
                        help=f"Seconds to wait between retries (default: {DEFAULT_RETRY_DELAY})")
    parser.add_argument("--sleep_delay", type=float, default=DEFAULT_SLEEP_DELAY,
                        help=f"Seconds to sleep between sending chunks (default: {DEFAULT_SLEEP_DELAY})")
    args = parser.parse_args()

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

    start_time = time.time()
    sender.open_connection()
    total_chunks, total_failures = sender.send_all_chunks()
    sender.close_connection()
    end_time = time.time()

    elapsed_seconds = end_time - start_time
    file_size = sender.get_file_size()
    formatted_elapsed = time.strftime("%H:%M:%S", time.gmtime(elapsed_seconds))
    total_attempts = total_chunks + total_failures
    speed = file_size / elapsed_seconds if elapsed_seconds > 0 else file_size

    summary = (
        "----- Execution Summary -----\n"
        f"Start Time:          {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}\n"
        f"End Time:            {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}\n"
        f"Time Elapsed:        {formatted_elapsed} (HH:MM:SS)\n"
        f"Total Chunks Sent:   {total_chunks}\n"
        f"Total Attempts:      {total_attempts} (includes {total_failures} retries)\n"
        f"Initial File Size:   {file_size} bytes\n"
        f"Transmission Speed:  {speed:.2f} bytes/second\n"
        "------------------------------"
    )
    logger.info(summary)

if __name__ == "__main__":
    main()
