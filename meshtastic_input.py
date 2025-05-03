#!/usr/bin/env python3
"""
Usage:
    python3 meshtastic_input.py log_file [--output_file output_file] [--log_level log_level] [--filter_header FILTER_HEADER]

Arguments:
    log_file: Path to the log file containing JSON messages.

Optional Arguments:
    --output_file: Path to the output file (default: combined_message.log).
    --log_level: Logging level (default: INFO).
    --filter_header: Only process messages whose header (the substring up to and including the first "!")
                     starts with this value. If not provided, all messages will be processed.
                     Note: Messages that consist solely of a header (with no content after "!") are skipped.

Examples:
    python3 meshtastic_input.py received_messages.log
    python3 meshtastic_input.py received_messages.log --output_file "custom_output.log"
    python3 meshtastic_input.py received_messages.log --log_level "DEBUG"
    python3 meshtastic_input.py received_messages.log --filter_header "ab"
"""

import json
import argparse
import logging
import re
import sys

# Create a module-level logger.
logger = logging.getLogger("MeshtasticInput")

# Global variable for header filter (if provided).
FILTER_HEADER = None

def read_and_concatenate_text(log_file):
    """
    Reads logged messages from a file, extracts the JSON portions from log entries,
    processes the "Text" field by removing its header (if present) using "!" as the delimiter,
    and concatenates the resulting message content.
    
    If --filter_header is provided, only messages whose header (up to and including the first "!")
    starts with that value are included.
    
    Args:
        log_file (str): Path to the log file.
    
    Returns:
        str: Concatenated message content from filtered JSON entries.
    """
    # Pattern matching a log entry line in our logger's format:
    # "YYYY-MM-DD HH:MM:SS,mmm - LEVEL - <JSON message>"
    header_pattern = re.compile(
        r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - (INFO|DEBUG|WARNING|ERROR) - (.*)$'
    )
    
    concatenated_texts = []
    current_entry = ""

    def process_entry(entry):
        """
        Attempts to decode the JSON entry and extract its "Text" field.
        - If the text contains "!", splits the string at the first "!".
          Everything up to and including "!" is considered the header and is removed.
          If the remaining content is empty, the entry is skipped.
        - If --filter_header is provided, then - for entries with a header - only messages
          whose header starts with that value are kept.
        - If no "!" is found in the text, the entire text is returned.
        """
        try:
            log_entry = json.loads(entry)
        except json.JSONDecodeError:
            logger.warning(f"Malformed JSON entry skipped: {entry}")
            return None

        text = log_entry.get("Text")
        if not text:
            return None

        if "!" in text:
            header_part, content = text.split("!", 1)
            header = header_part + "!"
            content = content.strip()
            if not content:
                # Skip messages that consist only of a header.
                return None
            if FILTER_HEADER is not None:
                if not header.startswith(FILTER_HEADER):
                    return None
            return content
        else:
            # If no header delimiter is found, return the entire text.
            return text

    try:
        with open(log_file, 'r') as f:
            for line in f:
                line = line.rstrip("\n")
                m = header_pattern.match(line)
                if m:
                    # Detected new log entry
                    if current_entry:
                        processed_text = process_entry(current_entry)
                        if processed_text:
                            concatenated_texts.append(processed_text)
                        current_entry = ""
                    # Start new entry using the JSON part of the line.
                    current_entry = m.group(2).strip()
                else:
                    # Continuation of a multi-line JSON message.
                    if current_entry:
                        current_entry += "\n" + line.strip()
                    else:
                        continue

                # If current entry appears complete, process it.
                if current_entry.endswith("}"):
                    processed_text = process_entry(current_entry)
                    if processed_text:
                        concatenated_texts.append(processed_text)
                    current_entry = ""
                    
            # Process any leftover entry.
            if current_entry:
                processed_text = process_entry(current_entry)
                if processed_text:
                    concatenated_texts.append(processed_text)
        
        return "".join(concatenated_texts)

    except FileNotFoundError:
        logger.error(f"Error: The file '{log_file}' was not found.")
        return ""
    except Exception as e:
        logger.error(f"Unexpected error while processing '{log_file}': {e}")
        return ""


def main():
    # Set up command-line argument parsing.
    parser = argparse.ArgumentParser(
        description="Process a log file and concatenate filtered messages (with headers removed)."
    )
    parser.add_argument("log_file", help="Path to the log file containing JSON messages.")
    parser.add_argument("--output_file", help="Path to the output file", default="combined_message.log")
    parser.add_argument("--log_level", help="Logging level (e.g., DEBUG, INFO)", default="INFO")
    parser.add_argument(
        "--filter_header",
        help="Filter for a specific header prefix. Only messages whose header (the substring up to and including the first '!') starts with this value are processed.",
        default=None
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
    if args.filter_header:
        logger.info(f"Filtering only messages with header starting with: '{args.filter_header}'")
    
    global FILTER_HEADER
    FILTER_HEADER = args.filter_header  # Set the module-level filter header.
    
    result = read_and_concatenate_text(args.log_file)
    
    if result:
        try:
            with open(args.output_file, 'w') as output_file:
                output_file.write(result)
            logger.info(f"Concatenated text written to '{args.output_file}'.")
        except Exception as e:
            logger.error(f"Could not write to '{args.output_file}': {e}")
            sys.exit(1)
    else:
        logger.info("No messages found that match the filtering criteria.")
        print("No messages found that match the filtering criteria.")


if __name__ == "__main__":
    main()
