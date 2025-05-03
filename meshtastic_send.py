#!/usr/bin/env python3
"""
MeshtasticSend - Split and send file content via Meshtastic

Usage:
    python3 meshtastic_send.py file_path --chunk_size CHUNK_SIZE [--ch_index CH_INDEX]
       [--dest DEST] [--connection CONNECTION] [--asynchronous] [--header HEADER]
       [--max_retries MAX_RETRIES] [--retry_delay RETRY_DELAY]
       [--max_concurrent_tasks MAX_CONCURRENT_TASKS]

Examples:
    python3 meshtastic_send.py combined_message.log --chunk_size 200 --ch_index 6 --dest '!47a78d36' --connection tcp
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --connection serial
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --asynchronous --header ab --connection tcp
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --asynchronous --header ab## --max_concurrent_tasks 2 --connection tcp

Description:
    This script reads the content of the specified text file, splits it into chunks,
    and sends each chunk using a Meshtastic command.
    
    It logs details of each send attempt—including retries with detailed error info—
    and prints a final summary with timing, file size, and calculated transmission speed.
    
    In synchronous (default) mode, messages are sent one after the other, preserving order.
    If the flag --asynchronous is given, asynchronous mode is enabled, and all messages are
    sent concurrently. The maximum number of concurrent tasks is limited by the --max_concurrent_tasks parameter.
    
    Additionally, if a header is supplied via --header, that header is prepended to each message.
    The header numbering is computed using the minimal number of digits required given the total number of chunks,
    unless the header template includes '#' placeholders.  
    Asynchronous log messages now also include "chunk x/y, attempt x/y, x remaining chunks".
"""

import argparse
import asyncio
import base64
import logging
import subprocess
import sys
import time
from pathlib import Path
import re

# Constants for defaults.
DEFAULT_MAX_RETRIES = 10
DEFAULT_RETRY_DELAY = 1  # seconds between retries
DEFAULT_MAX_CONCURRENT_TASKS = 4

def setup_logging():
    """Configure console and file logging; console shows INFO+."""
    logger = logging.getLogger("MeshtasticSender")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    file_handler = logging.FileHandler("debug_messages.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

logger = setup_logging()

class MeshtasticSender:
    """
    Handles file reading, chunking, and sending via Meshtastic.
    Supports synchronous and asynchronous sending.
    If a header template is provided (via --header), it is prepended to each message.
    The header numbering uses the minimal digit width (based on total chunk count) if no '#' is present.
    Asynchronous mode is enabled with the --asynchronous switch.
    Concurrency is limited by a semaphore.
    """
    def __init__(self, file_path: Path, chunk_size: int, ch_index: int, dest: str,
                 connection: str, max_retries: int = DEFAULT_MAX_RETRIES,
                 retry_delay: int = DEFAULT_RETRY_DELAY,
                 asynchronous_mode: bool = False,
                 header_template: str = None,
                 max_concurrent_tasks: int = DEFAULT_MAX_CONCURRENT_TASKS):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.ch_index = ch_index
        self.dest = dest
        self.connection = connection.lower()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.asynchronous_mode = asynchronous_mode
        self.header_template = header_template  # may be None
        self.max_concurrent_tasks = max_concurrent_tasks

    def read_file(self) -> str:
        try:
            return self.file_path.read_text()
        except Exception as e:
            logger.error(f"Error reading file '{self.file_path}': {e}")
            sys.exit(1)

    def get_file_size(self) -> int:
        return self.file_path.stat().st_size

    def encode_file_base64(self, content: str) -> bytes:
        return base64.b64encode(content.encode('utf-8'))

    def chunk_content(self, content: str) -> list:
        return [content[i:i + self.chunk_size] for i in range(0, len(content), self.chunk_size)]

    def generate_header(self, index: int, total_chunks: int) -> str:
        """
        Generate a header for chunk 'index' based on the header template.
        If no header_template is provided, returns an empty string.
        
        If the header template contains '#' characters, they are used as placeholders.
        Otherwise, compute the minimal digit width based on total_chunks.
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

    def build_command(self, text: str) -> list:
        command = ['meshtastic']
        if self.connection == 'tcp':
            command.append('--host')
        elif self.connection == 'serial':
            command.append('--serial')
        command.extend(['--ack', '--sendtext', text])
        if self.ch_index is not None:
            command.extend(['--ch-index', str(self.ch_index)])
        if self.dest is not None:
            command.extend(['--dest', self.dest])
        return command

    def log_retry_error(self, command: list, e: subprocess.CalledProcessError, attempt: int):
        detailed_error = (
            f"Command: {' '.join(command)}; "
            f"Exit code: {e.returncode}; "
            f"STDOUT: {e.stdout.strip() if e.stdout else 'None'}; "
            f"STDERR: {e.stderr.strip() if e.stderr else 'None'}"
        )
        logger.warning(f"Retry {attempt}/{self.max_retries} returned exit status {e.returncode}. Details: {detailed_error}")

    def send_chunks_sync(self, chunks: list) -> tuple:
        """Send all chunks synchronously."""
        total_chunks = len(chunks)
        total_failures = 0
        
        for i, chunk in enumerate(chunks, start=1):
            if self.header_template:
                header = self.generate_header(i, total_chunks)
                message = header + chunk
            else:
                message = chunk

            command = self.build_command(message)
            attempt = 0
            while attempt < self.max_retries:
                try:
                    subprocess.run(command, check=True, capture_output=True, text=True)
                    logger.info(f"Successfully sent chunk {i}/{total_chunks} with header '{header}' (Attempt {attempt+1}/{self.max_retries})")
                    break
                except subprocess.CalledProcessError as e:
                    attempt += 1
                    total_failures += 1
                    self.log_retry_error(command, e, attempt)
                    time.sleep(self.retry_delay)
                    if attempt == self.max_retries:
                        logger.error(f"Aborting after {self.max_retries} retries for chunk {i}.")
                        sys.exit(1)
        logger.info(f"Total failures/retries: {total_failures}")
        return total_chunks, total_failures

    async def limited_send_chunk(self, chunk: str, header: str, sem: asyncio.Semaphore, index: int, total_chunks: int) -> int:
        async with sem:
            return await self.send_chunk_async_with_header(chunk, header, index, total_chunks)

    async def send_chunk_async_with_header(self, chunk: str, header: str, index: int, total_chunks: int) -> int:
        """
        Sends a chunk asynchronously with the provided header.
        Logs includes "chunk x/y, attempt x/y, and x remaining chunks".
        Returns the number of retries performed.
        """
        message = header + chunk
        command = self.build_command(message)
        attempt = 0
        while attempt < self.max_retries:
            logger.debug(f"About to execute command: {' '.join(command)} (Attempt {attempt+1})")
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                logger.debug(f"Command launched for header '{header}', awaiting result...")
                stdout, stderr = await proc.communicate()
                logger.debug(f"Command for header '{header}' finished with return code: {proc.returncode}")
                if proc.returncode == 0:
                    remaining = total_chunks - index
                    logger.info(f"Successfully sent async chunk with header '{header}' (chunk {index}/{total_chunks}, Attempt {attempt+1}/{self.max_retries}, {remaining} remaining chunks)")
                    return attempt
                else:
                    raise subprocess.CalledProcessError(proc.returncode, command, output=stdout, stderr=stderr)
            except subprocess.CalledProcessError as e:
                attempt += 1
                self.log_retry_error(command, e, attempt)
                await asyncio.sleep(self.retry_delay)
                if attempt == self.max_retries:
                    logger.error(f"Aborting after {self.max_retries} retries for async chunk with header '{header}'.")
                    sys.exit(1)
        return attempt

    async def send_chunks_async(self, chunks: list) -> tuple:
        """Asynchronously send all chunks with concurrency limited by a semaphore."""
        total_chunks = len(chunks)
        sem = asyncio.Semaphore(self.max_concurrent_tasks)
        tasks = []
        for i, chunk in enumerate(chunks, start=1):
            if self.header_template:
                header = self.generate_header(i, total_chunks)
            else:
                header = ""
            task = asyncio.create_task(self.limited_send_chunk(chunk, header, sem, i, total_chunks))
            tasks.append(task)
        results = await asyncio.gather(*tasks)
        total_failures = sum(results)
        logger.info(f"Total failures/retries (async): {total_failures}")
        return total_chunks, total_failures

def main():
    parser = argparse.ArgumentParser(description="Send file content via Meshtastic with chunking.")
    parser.add_argument("file_path", help="Path to the text file")
    parser.add_argument("--chunk_size", type=int, default=200, help="Maximum length of each chunk")
    parser.add_argument("--ch_index", type=int, help="Channel index for the Meshtastic command")
    parser.add_argument("--dest", type=str, help="Destination for the Meshtastic command")
    parser.add_argument("--connection", type=str, choices=['tcp', 'serial'], default='tcp',
                        help="Connection mode: 'tcp' or 'serial'")
    parser.add_argument("--asynchronous", action="store_true",
                        help="Enable asynchronous mode")
    parser.add_argument("--header", type=str,
                        help="Header template to prepend to each message. Use '#' to indicate digit placeholders. "
                             "If not specified, no header is prepended. If specified without '#', minimal digit width is used based on total chunks.")
    parser.add_argument("--max_retries", type=int, default=DEFAULT_MAX_RETRIES,
                        help=f"Maximum number of retries per chunk (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--retry_delay", type=int, default=DEFAULT_RETRY_DELAY,
                        help=f"Seconds to wait between retries (default: {DEFAULT_RETRY_DELAY})")
    parser.add_argument("--max_concurrent_tasks", type=int, default=DEFAULT_MAX_CONCURRENT_TASKS,
                        help=f"Maximum number of concurrent asynchronous tasks (default: {DEFAULT_MAX_CONCURRENT_TASKS})")
    args = parser.parse_args()

    file_path = Path(args.file_path)
    sender = MeshtasticSender(
        file_path=file_path,
        chunk_size=args.chunk_size,
        ch_index=args.ch_index,
        dest=args.dest,
        connection=args.connection,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
        asynchronous_mode=args.asynchronous,
        header_template=args.header,
        max_concurrent_tasks=args.max_concurrent_tasks
    )

    start_time = time.time()
    file_content = sender.read_file()
    file_size = sender.get_file_size()
    _ = sender.encode_file_base64(file_content)  # computed but not used in summary.
    chunks = sender.chunk_content(file_content)

    if args.asynchronous:
        total_chunks, total_failures = asyncio.run(sender.send_chunks_async(chunks))
    else:
        total_chunks, total_failures = sender.send_chunks_sync(chunks)

    end_time = time.time()
    elapsed_seconds = end_time - start_time
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
