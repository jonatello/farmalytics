#!/usr/bin/env python3
"""
Usage:
    python3 your_script.py log_file [--start_time "YYYY-MM-DD HH:MM:SS"] [--end_time "YYYY-MM-DD HH:MM:SS"] [--output_file output_file] [--log_level log_level]

Arguments:
    log_file: Path to the log file containing JSON messages.

Optional Arguments:
    --start_time: Start time in 'YYYY-MM-DD HH:MM:SS' format (default: 24 hours ago).
    --end_time: End time in 'YYYY-MM-DD HH:MM:SS' format (default: current time).
    --output_file: Path to the output file (default: combined_message.log).
    --log_level: Logging level (default: INFO).

Examples:
    python3 your_script.py received_messages.log
    python3 your_script.py received_messages.log --start_time "2025-04-17 12:00:00" --end_time "2025-04-18 12:00:00"
    python3 your_script.py received_messages.log --output_file "custom_output.log"
    python3 your_script.py received_messages.log --log_level "DEBUG"
    python3 your_script.py received_messages.log --start_time "2025-04-17 12:00:00" --end_time "2025-04-18 12:00:00" --output_file "custom_output.log" --log_level "DEBUG"
"""

import json
import argparse
import logging
from datetime import datetime, timedelta

def read_and_concatenate_text(log_file, start_time, end_time):
    """
    Reads logged messages from a file, filters by timeframe, and concatenates Text values.

    Args:
        log_file (str): Path to the log file containing JSON messages.
        start_time (int): Start timeframe in epoch seconds.
        end_time (int): End timeframe in epoch seconds.

    Returns:
        str: Concatenated Text values from filtered log entries.
    """
    concatenated_texts = []  # List to accumulate text values

    try:
        with open(log_file, 'r') as file:
            current_entry = ""  # Buffer for multiline JSON

            for line in file:
                line = line.strip()  # Remove leading/trailing whitespace
                if not line:  # Skip empty lines
                    continue

                # Accumulate lines for a single JSON object
                current_entry += line
                if line.endswith("}"):  # Check if JSON object ends
                    try:
                        log_entry = json.loads(current_entry)  # Parse JSON
                        rx_time = log_entry.get("RXTime")  # Get RXTime value
                        text = log_entry.get("Text")  # Get Text value

                        # Filter entries within the specified timeframe
                        if rx_time and start_time <= int(rx_time) <= end_time and text:
                            concatenated_texts.append(text)  # Add text to the list

                    except json.JSONDecodeError:
                        logging.warning(f"Malformed entry: {current_entry}")  # Log warning for malformed entry
                    finally:
                        current_entry = ""  # Reset buffer after processing

        # Join texts without extra whitespace
        return "".join(concatenated_texts)

    except FileNotFoundError:
        logging.error(f"Error: The file '{log_file}' was not found.")  # Log error if file not found
        return ""
    except Exception as e:
        logging.error(f"Error: An unexpected error occurred: {e}")  # Log any other unexpected errors
        return ""

def parse_time(time_str):
    """
    Parse a human-readable time string into epoch seconds.

    Args:
        time_str (str): Human-readable time string.

    Returns:
        int: Time in epoch seconds.
    """
    try:
        return int(datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").timestamp())
    except ValueError:
        logging.error(f"Error: Invalid time format '{time_str}'. Use 'YYYY-MM-DD HH:MM:SS'.")  # Log error for invalid time format
        raise

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Process log file and concatenate messages.")
    parser.add_argument("log_file", help="Path to the log file")
    parser.add_argument("--start_time", help="Start time in 'YYYY-MM-DD HH:MM:SS' format", default=(datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"))
    parser.add_argument("--end_time", help="End time in 'YYYY-MM-DD HH:MM:SS' format", default=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    parser.add_argument("--output_file", help="Path to the output file", default="combined_message.log")
    parser.add_argument("--log_level", help="Logging level", default="INFO")

    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s - %(levelname)s - %(message)s")

    # Parse start and end times
    try:
        start_time_epoch = parse_time(args.start_time)
        end_time_epoch = parse_time(args.end_time)
    except ValueError:
        parser.error("Invalid time format. Use 'YYYY-MM-DD HH:MM:SS'.")

    # Call the function and output the concatenated text
    result = read_and_concatenate_text(args.log_file, start_time_epoch, end_time_epoch)

    if result:
        print(result)
        # Write the result to a new file
        try:
            with open(args.output_file, "w") as output_file:
                output_file.write(result)
        except Exception as e:
            logging.error(f"Error: Could not write to '{args.output_file}': {e}")  # Log error if writing to file fails
    else:
        print("No messages found within the specified timeframe.")
