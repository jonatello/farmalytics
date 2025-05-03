#!/usr/bin/env python3
"""
Usage:
    python3 meshtastic_bench.py [--initial_chunk_size INITIAL_CHUNK_SIZE]
         [--success_threshold SUCCESS_THRESHOLD] [--increment INCREMENT]
         [--max_chunk_size MAX_CHUNK_SIZE] [--max_retries MAX_RETRIES] [--run_time RUN_TIME]
         [--ch_index CH_INDEX] [--dest DEST] [--connection CONNECTION] [--send_verbose]

Arguments:
    --initial_chunk_size   Starting chunk size (default: 100)
    --success_threshold    Number of consecutive successful transmissions required 
                           before increasing the chunk size (default: 3)
    --increment            Amount to increase chunk size when threshold is met (default: 50)
    --max_chunk_size       Maximum allowed chunk size (default: 240)
    --max_retries          Maximum retries per transmission attempt (default: 5)
    --run_time             Total run time in minutes for the benchmark (default: 60)
    --ch_index             (Optional) Channel index for the meshtastic command
    --dest                 (Optional) Destination for the meshtastic command
    --connection           Connection mode: 'tcp' or 'serial' (default: tcp)
    --send_verbose         If set, passes the debug flag (i.e. '--debug') to the meshtastic command

Description:
    This benchmarking script continuously sends randomly generated strings using meshtastic.
    Each message's length equals the current chunk size. After a number of consecutive
    successful sends (default 3) for a given chunk size, the program increases the chunk size
    by a set increment (default 50) but up to a maximum value (default 240). If a transmission 
    fails, the consecutive success count is reset. The script runs for the designated total 
    runtime, and if interrupted via Ctrl+C (or when the run time is met) the script produces a 
    summary including total attempts, total failures, total retries, final chunk size, and elapsed time.
"""

import subprocess
import argparse
import logging
import time
import sys
import random
import string

# ---------------------- Utility Functions ----------------------

def generate_random_string(length):
    """
    Generates a random string of the specified length.
    
    Parameters:
        length (int): Length of the string.
    
    Returns:
        str: A random string of the given length.
    """
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def send_random_chunk(chunk, ch_index, dest, connection_mode, max_retries, send_verbose=False):
    """
    Attempts to send the provided chunk using the meshtastic command.
    Uses a retry mechanism with exponential backoff.
    
    Parameters:
        chunk (str): The message to send.
        ch_index (int|None): Optional channel index.
        dest (str|None): Optional destination.
        connection_mode (str): 'tcp' or 'serial'
        max_retries (int): Maximum retries per transmission.
        send_verbose (bool): If True, include the debug flag in the command.
    
    Returns:
        tuple: (success, retry_count)
               success (bool): True if transmission succeeded, False otherwise.
               retry_count (int): Number of retries performed (0 if sent on first try).
    """
    command = ['meshtastic']
    if connection_mode == 'tcp':
        command.append('--host')
    elif connection_mode == 'serial':
        command.append('--serial')
    if send_verbose:
        # Use the supported debug flag (instead of --verbose) so that extra output from meshtastic is provided.
        command.append('--debug')
    command.extend(['--ack', '--sendtext', chunk])
    if ch_index is not None:
        command.extend(['--ch-index', str(ch_index)])
    if dest is not None:
        command.extend(['--dest', dest])
    
    retries = 0
    while retries < max_retries:
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            logger.info(f"Successfully sent chunk of size {len(chunk)} (Attempt {retries+1}/{max_retries})")
            return (True, retries)
        except subprocess.CalledProcessError as e:
            retries += 1
            # Log the full command, the exit code, stdout and stderr.
            err_msg = (f"Command '{' '.join(command)}' failed with exit code {e.returncode}. "
                       f"STDOUT: {e.stdout.strip() if e.stdout else 'None'}, "
                       f"STDERR: {e.stderr.strip() if e.stderr else 'None'}")
            logger.warning(f"Retry {retries}/{max_retries} for chunk size {len(chunk)} due to error: {err_msg}")
            time.sleep(2 ** retries)  # Exponential backoff
    logger.error(f"Failed to send chunk size {len(chunk)} after {max_retries} retries.")
    return (False, retries)

# ---------------------- Main Execution Flow ----------------------

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark meshtastic transmission by sending random strings"
    )
    parser.add_argument("--initial_chunk_size", type=int, default=100,
                        help="Starting chunk size (default: 100)")
    parser.add_argument("--success_threshold", type=int, default=3,
                        help="Consecutive successes required before increasing chunk size (default: 3)")
    parser.add_argument("--increment", type=int, default=50,
                        help="Increase chunk size by this many characters when threshold is met (default: 50)")
    parser.add_argument("--max_chunk_size", type=int, default=240,
                        help="Maximum allowed chunk size (default: 240)")
    parser.add_argument("--max_retries", type=int, default=5,
                        help="Maximum retries per transmission attempt (default: 5)")
    parser.add_argument("--run_time", type=int, default=60,
                        help="Total run time in minutes for the benchmark (default: 60)")
    parser.add_argument("--ch_index", type=int, help="Channel index for the meshtastic command")
    parser.add_argument("--dest", type=str, help="Destination for the meshtastic command")
    parser.add_argument("--connection", type=str, choices=['tcp', 'serial'], default='tcp',
                        help="Connection mode: 'tcp' or 'serial' (default: tcp)")
    parser.add_argument("--send_verbose", action="store_true",
                        help="If set, passes the debug flag (i.e. '--debug') to the meshtastic command")
    args = parser.parse_args()
    
    # Configure logging.
    logging.basicConfig(level=logging.INFO, 
                        format="%(asctime)s - %(levelname)s - %(message)s")
    global logger
    logger = logging.getLogger()
    
    start_time = time.time()
    run_time_seconds = args.run_time * 60
    
    current_chunk_size = args.initial_chunk_size
    consecutive_success = 0
    total_attempts = 0
    total_failures = 0
    total_retries = 0
    
    logger.info(f"Starting benchmark: initial chunk size {current_chunk_size}, run time {args.run_time} minutes.")
    
    try:
        while time.time() - start_time < run_time_seconds:
            if current_chunk_size > args.max_chunk_size:
                current_chunk_size = args.max_chunk_size
            
            # Generate a random string for the current chunk size.
            chunk = generate_random_string(current_chunk_size)
            total_attempts += 1
            logger.info(f"Attempting to send chunk of size {current_chunk_size} (Total attempt {total_attempts}).")
            
            success, retries = send_random_chunk(chunk, args.ch_index, args.dest,
                                                 args.connection, args.max_retries,
                                                 send_verbose=args.send_verbose)
            total_retries += retries
            
            if success:
                consecutive_success += 1
                logger.info(f"Transmission successful; consecutive successes: {consecutive_success}.")
                if consecutive_success >= args.success_threshold:
                    if current_chunk_size < args.max_chunk_size:
                        new_size = current_chunk_size + args.increment
                        if new_size > args.max_chunk_size:
                            new_size = args.max_chunk_size
                        logger.info(f"Threshold reached; increasing chunk size from {current_chunk_size} to {new_size}.")
                        current_chunk_size = new_size
                    else:
                        logger.info("Maximum chunk size reached; continuing at maximum size.")
                    consecutive_success = 0
            else:
                consecutive_success = 0
                total_failures += 1
                
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Benchmark interrupted by user. Finalizing summary...")
    finally:
        elapsed_seconds = time.time() - start_time
        logger.info("----- Benchmark Summary -----")
        logger.info(f"Total Attempts: {total_attempts}")
        logger.info(f"Total Failures: {total_failures}")
        logger.info(f"Total Retries: {total_retries}")
        logger.info(f"Final Chunk Size: {current_chunk_size}")
        logger.info(f"Elapsed Time: {time.strftime('%H:%M:%S', time.gmtime(elapsed_seconds))}")

if __name__ == "__main__":
    main()
