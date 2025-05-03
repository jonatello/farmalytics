#!/usr/bin/env python3
"""
MeshtasticSend - Split and send file content via Meshtastic

Usage:
    python3 meshtastic_send.py file_path --chunk_size CHUNK_SIZE [--ch_index CH_INDEX]
       [--dest DEST] [--connection CONNECTION] [--asynchronous HEADER]
       [--max_retries MAX_RETRIES] [--retry_delay RETRY_DELAY]
       [--max_concurrent_tasks MAX_CONCURRENT_TASKS]

Examples:
    python3 meshtastic_send.py combined_message.log --chunk_size 200 --ch_index 6 --dest '!47a78d36' --connection tcp
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --connection serial
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --asynchronous ab## --connection tcp
    python3 meshtastic_send.py combined_message.log --chunk_size 150 --asynchronous ab## --max_concurrent_tasks 4 --connection tcp

Description:
    This script reads the content of the specified text file, splits it into chunks,
    and sends each chunk using a Meshtastic command.
    
    It logs details of each send attempt—including retries with detailed error info—
    and prints a final summary with timing, file size, and calculated transmission speed.
    
    In synchronous (default) mode, messages are sent one after the other (order preserved).
    In asynchronous mode (enabled via the --asynchronous option), the supplied header template
    is used to prepend a unique header (with a numeric counter) to each message, and messages are
    sent concurrently. The maximum number of concurrent tasks is limited by the --max_concurrent_tasks parameter.
    
    Instead of exponential backoff, a constant retry delay is used (specified by --retry_delay).
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
    """Configure console (INFO+) and file (DEBUG) logging and return the logger."""
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
    Encapsulates file reading, content chunking, and sending via Meshtastic.
    Supports both synchronous and asynchronous (concurrent) modes.
    In async mode, a header template is used to prepend a unique header with a numeric counter.
    The maximum number of concurrent asynchronous tasks is limited by a semaphore.
    """
    def __init__(self, file_path: Path, chunk_size: int, ch_index: int, dest: str,
                 connection: str, max_retries: int = DEFAULT_MAX_RETRIES,
                 retry_delay: int = DEFAULT_RETRY_DELAY,
                 asynchronous_header: str = None,
                 max_concurrent_tasks: int = DEFAULT_MAX_CONCURRENT_TASKS):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.ch_index = ch_index
        self.dest = dest
        self.connection = connection.lower()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.async_header = asynchronous_header  # non-None enables async mode
        self.max_concurrent_tasks = max_concurrent_tasks

    def read_file(self) -> str:
        """Read file content using pathlib."""
        try:
            return self.file_path.read_text()
        except Exception as e:
            logger.error(f"Error reading file '{self.file_path}': {e}")
            sys.exit(1)

    def get_file_size(self) -> int:
        """Return file size in bytes."""
        return self.file_path.stat().st_size

    def encode_file_base64(self, content: str) -> bytes:
        """Return base64-encoded version of the content."""
        return base64.b64encode(content.encode('utf-8'))

    def chunk_content(self, content: str) -> list:
        """Split content into chunks of length chunk_size."""
        return [content[i:i + self.chunk_size] for i in range(0, len(content), self.chunk_size)]

    def build_command(self, text: str) -> list:
        """
        Build the Meshtastic command list.
        The text provided is the message to send.
        """
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
        """
        Log detailed error info on a retry attempt.
        """
        detailed_error = (
            f"Command: {' '.join(command)}; "
            f"Exit code: {e.returncode}; "
            f"STDOUT: {e.stdout.strip() if e.stdout else 'None'}; "
            f"STDERR: {e.stderr.strip() if e.stderr else 'None'}"
        )
        logger.warning(f"Retry {attempt}/{self.max_retries} returned exit status {e.returncode}. Details: {detailed_error}")

    def send_chunks_sync(self, chunks: list) -> tuple:
        """Send all chunks synchronously (sequentially)."""
        total_chunks = len(chunks)
        total_failures = 0

        for i, chunk in enumerate(chunks, start=1):
            command = self.build_command(chunk)
            attempt = 0
            while attempt < self.max_retries:
                try:
                    subprocess.run(command, check=True, capture_output=True, text=True)
                    logger.info(f"Successfully sent chunk {i}/{total_chunks}: {chunk[:50]}...")
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

    def generate_async_header(self, index: int) -> str:
        """
        Generate a header for a given chunk index based on the asynchronous header template.
        
        If the template contains '#' characters, they are replaced by a zero-padded counter,
        with the number of digits determined by the number of consecutive '#' characters.
        If no '#' is present, a default 4-digit counter and an exclamation mark are appended.
        """
        template = self.async_header
        if '#' in template:
            pattern = re.compile(r"(#+)")
            match = pattern.search(template)
            if match:
                width = len(match.group(0))
                counter_str = f"{index:0{width}d}"
                header = pattern.sub(counter_str, template, count=1)
                return header
            else:
                return f"{template}{index:04d}!"
        else:
            return f"{template}{index:04d}!"

    async def limited_send_chunk(self, chunk: str, header: str, sem: asyncio.Semaphore) -> int:
        """
        Wrapper function that acquires the semaphore and sends a chunk asynchronously.
        Returns the number of retries for that chunk.
        """
        async with sem:
            return await self.send_chunk_async_with_header(chunk, header)

    async def send_chunk_async_with_header(self, chunk: str, header: str) -> int:
        """
        Send a single chunk asynchronously.
        The provided header is prepended to the chunk.
        Returns the number of retries performed.
        """
        message = header + chunk
        command = self.build_command(message)
        attempt = 0
        while attempt < self.max_retries:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0:
                    logger.info(f"Successfully sent async chunk with header '{header}' (Attempt {attempt+1}/{self.max_retries})")
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
        """
        Asynchronously send all chunks concurrently, limiting concurrency via a semaphore.
        The asynchronous header template is used to generate a unique header for each chunk.
        Order of sending is not preserved.
        """
        sem = asyncio.Semaphore(self.max_concurrent_tasks)
        total_chunks = len(chunks)
        tasks = []
        for i, chunk in enumerate(chunks, start=1):
            header = self.generate_async_header(i)
            task = asyncio.create_task(self.limited_send_chunk(chunk, header, sem))
            tasks.append(task)
        results = await asyncio.gather(*tasks)
        total_failures = sum(results)
        logger.info(f"Total failures/retries (async): {total_failures}")
        return total_chunks, total_failures

def main():
    parser = argparse.ArgumentParser(
        description="Send file content via Meshtastic with chunking."
    )
    parser.add_argument("file_path", help="Path to the text file")
    parser.add_argument("--chunk_size", type=int, default=200, help="Maximum length of each chunk")
    parser.add_argument("--ch_index", type=int, help="Channel index for the Meshtastic command")
    parser.add_argument("--dest", type=str, help="Destination for the Meshtastic command")
    parser.add_argument("--connection", type=str, choices=['tcp', 'serial'], default='tcp',
                        help="Connection mode: 'tcp' or 'serial'")
    parser.add_argument("--asynchronous", type=str,
                        help="Enable asynchronous mode with this header template. "
                             "Use '#' to indicate digit placeholders (e.g., 'ab##' for two-digit counters). "
                             "If no '#' is present, a default 4-digit counter and an exclamation mark will be appended.")
    parser.add_argument("--max_retries", type=int, default=DEFAULT_MAX_RETRIES,
                        help=f"Maximum number of retries per chunk (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--retry_delay", type=int, default=DEFAULT_RETRY_DELAY,
                        help=f"Number of seconds to wait between retries (default: {DEFAULT_RETRY_DELAY})")
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
        asynchronous_header=args.asynchronous,
        max_concurrent_tasks=args.max_concurrent_tasks
    )

    start_time = time.time()
    file_content = sender.read_file()
    file_size = sender.get_file_size()
    _ = sender.encode_file_base64(file_content)  # Computed but not used in summary.
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
