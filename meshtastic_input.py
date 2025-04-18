#!/usr/bin/env python3
import json
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
    concatenated_texts = []  # Use a list to accumulate text values
    current_entry = ""  # Buffer for multiline JSON

    try:
        with open(log_file, 'r') as file:
            for line in file:
                line = line.strip()
                if not line:  # Skip empty lines
                    continue

                # Accumulate lines for a single JSON object
                current_entry += line
                if line.endswith("}"):  # JSON object ends
                    try:
                        log_entry = json.loads(current_entry)  # Parse JSON
                        rx_time = log_entry.get("RXTime", None)
                        text = log_entry.get("Text", None)

                        # Filter entries within the specified timeframe
                        if rx_time is not None and start_time <= int(rx_time) <= end_time:
                            if text:
                                concatenated_texts.append(text)  # Add text to the list

                    except json.JSONDecodeError:
                        # Skip malformed entries
                        pass
                    finally:
                        current_entry = ""  # Reset buffer after processing

        # Join texts without extra whitespace
        return "".join(concatenated_texts)

    except FileNotFoundError:
        return ""

if __name__ == "__main__":
    # Path to the log file
    log_file = "received_messages.log"

    # Define the timeframe (defaulting to the past 24 hours)
    end_time_epoch = int(datetime.utcnow().timestamp())  # Current time
    start_time_epoch = int((datetime.utcnow() - timedelta(days=1)).timestamp())  # 24 hours ago

    # Call the function and output the concatenated text
    result = read_and_concatenate_text(log_file, start_time_epoch, end_time_epoch)

    if result:
        print(result)
    else:
        print("No messages found within the specified timeframe.")
