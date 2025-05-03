#!/usr/bin/env python3
"""
Usage:
    python3 meshtastic_input.py log_file [--start_time "YYYY-MM-DD HH:MM:SS"]
        [--end_time "YYYY-MM-DD HH:MM:SS"] [--output_file output_file] [--log_level log_level]

Arguments:
    log_file: Path to the log file containing JSON messages.

Optional Arguments:
    --start_time: Start time in 'YYYY-MM-DD HH:MM:SS' format (default: 24 hours ago).
    --end_time: End time in 'YYYY-MM-DD HH:MM:SS' format (default: current time).
    --output_file: Path to the output file (default: combined_message.log).
    --log_level: Logging level (default: INFO).

Examples:
    python3 meshtastic_input.py received_messages.log
    python3 meshtastic_input.py received_messages.log --start_time "2025-04-17 12:00:00" --end_time "2025-04-18 12:00:00"
    python3 meshtastic_input.py received_messages.log --output_file "custom_output.log"
    python3 meshtastic_input.py received_messages.log --log_level "DEBUG"
    python3 meshtastic_input.py received_messages.log --start_time "2025-04-17 12:00:00" \
        --end_time "2025-04-18 12:00:00" --output_file "custom_output.log" --log_level "DEBUG"
"""

import json
import argparse
import logging
from datetime import datetime, timedelta
import re
import sys

# Create a module-level logger.
logger = logging.getLogger("MeshtasticInput")


def read_and_concatenate_text(log_file, start_time, end_time):
    """
    Reads logged messages from a file, extracts the JSON portions from log entries,
    filters by timeframe (using RXTime), and concatenates the "Text" values.
    
    The log file is assumed to be in the format produced by the logger:
      <timestamp> - <LEVEL> - <JSON message>
    The JSON message may span multiple lines.
    
    Args:
        log_file (str): Path to the log file.
        start_time (int): Start time (epoch seconds).
        end_time (int): End time (epoch seconds).
    
    Returns:
        str: Concatenated Text values from filtered JSON entries.
    """
    # This pattern expects log lines starting with a timestamp, level and then a message.
    header_pattern = re.compile(
        r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - (INFO|DEBUG|WARNING|ERROR) - (.*)$'
    )
    
    concatenated_texts = []
    current_entry = ""

    try:
        with open(log_file, 'r') as f:
            for line in f:
                line = line.rstrip("\n")
                m = header_pattern.match(line)
                if m:
                    # We have detected a new log entry.
                    if current_entry:
                        # Process the previously accumulated JSON block.
                        try:
                            log_entry = json.loads(current_entry)
                            rx_time = log_entry.get("RXTime")
                            text = log_entry.get("Text")
                            if rx_time and text:
                                try:
                                    rx_time_int = int(rx_time)
                                    if start_time <= rx_time_int <= end_time:
                                        concatenated_texts.append(text)
                                except ValueError:
                                    logger.warning(f"Invalid RXTime value: {rx_time} in entry: {current_entry}")
                        except json.JSONDecodeError:
                            logger.warning(f"Malformed JSON entry skipped: {current_entry}")
                        current_entry = ""
                    # Start a new JSON block using the portion after the header.
                    current_entry = m.group(2).strip()
                else:
                    # If the line doesn't match the header, assume it's a continuation of the current entry.
                    if current_entry:
                        current_entry += "\n" + line.strip()
                    else:
                        # No current entry; skip line.
                        continue

                # Optionally, if the current block seems finished (endswith a '}'), process it.
                if current_entry.endswith("}"):
                    try:
                        log_entry = json.loads(current_entry)
                        rx_time = log_entry.get("RXTime")
                        text = log_entry.get("Text")
                        if rx_time and text:
                            try:
                                rx_time_int = int(rx_time)
                                if start_time <= rx_time_int <= end_time:
                                    concatenated_texts.append(text)
                            except ValueError:
                                logger.warning(f"Invalid RXTime value: {rx_time} in entry: {current_entry}")
                    except json.JSONDecodeError:
                        logger.warning(f"Malformed JSON entry skipped: {current_entry}")
                    current_entry = ""
                    
            # Process any leftover entry at EOF.
            if current_entry:
                try:
                    log_entry = json.loads(current_entry)
                    rx_time = log_entry.get("RXTime")
                    text = log_entry.get("Text")
                    if rx_time and text:
                        try:
                            rx_time_int = int(rx_time)
                            if start_time <= rx_time_int <= end_time:
                                concatenated_texts.append(text)
                        except ValueError:
                            logger.warning(f"Invalid RXTime value: {rx_time} in entry: {current_entry}")
                except json.JSONDecodeError:
                    logger.warning(f"Malformed JSON entry skipped: {current_entry}")
        
        return "".join(concatenated_texts)

    except FileNotFoundError:
        logger.error(f"Error: The file '{log_file}' was not found.")
        return ""
    except Exception as e:
        logger.error(f"Unexpected error while processing '{log_file}': {e}")
        return ""


def parse_time(time_str):
    """
    Parse a human-readable time string in 'YYYY-MM-DD HH:MM:SS' format into epoch seconds.
    
    Args:
        time_str (str): Time string.
    
    Returns:
        int: Corresponding epoch seconds.
    """
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())
    except ValueError as ve:
        logger.error(f"Invalid time format '{time_str}'. Use 'YYYY-MM-DD HH:MM:SS'.")
        raise ve


def main():
    # Set up command-line argument parsing.
    parser = argparse.ArgumentParser(description="Process a log file and concatenate filtered messages.")
    parser.add_argument("log_file", help="Path to the log file containing JSON messages.")
    parser.add_argument(
        "--start_time",
        help="Start time in 'YYYY-MM-DD HH:MM:SS' format",
        default=(datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    )
    parser.add_argument(
        "--end_time",
        help="End time in 'YYYY-MM-DD HH:MM:SS' format",
        default=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    )
    parser.add_argument(
        "--output_file",
        help="Path to the output file",
        default="combined_message.log"
    )
    parser.add_argument(
        "--log_level",
        help="Logging level (e.g., DEBUG, INFO)",
        default="INFO"
    )
    
    args = parser.parse_args()
    
    # Configure logging.
    numeric_level = getattr(logging, args.log_level.upper(), None)
    if not isinstance(numeric_level, int):
        parser.error(f"Invalid log level: {args.log_level}")
    logger.setLevel(numeric_level)
    
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    logger.addHandler(console_handler)
    
    logger.info(f"Processing log file: {args.log_file}")
    logger.info(f"Filtering messages from {args.start_time} to {args.end_time}")
    
    try:
        start_epoch = parse_time(args.start_time)
        end_epoch = parse_time(args.end_time)
    except ValueError:
        parser.error("Invalid time format provided. Use 'YYYY-MM-DD HH:MM:SS'.")
    
    # Process the log file and get concatenated text.
    result = read_and_concatenate_text(args.log_file, start_epoch, end_epoch)
    
    if result:
        try:
            with open(args.output_file, 'w') as output_file:
                output_file.write(result)
            logger.info(f"Concatenated text written to '{args.output_file}'.")
        except Exception as e:
            logger.error(f"Could not write to '{args.output_file}': {e}")
            sys.exit(1)
    else:
        logger.info("No messages found within the specified timeframe.")
        print("No messages found within the specified timeframe.")


if __name__ == "__main__":
    main()
