#!/usr/bin/env python3
"""
meshtastic_input.py

This script reads a log file containing Meshtastic messages logged as JSON.
It extracts the "Text" field from each JSON object. If a header filter is specified via --header,
the script will:
  1. Filter messages whose Text field starts with the given header followed by a numeric part and an exclamation mark.
  2. Extract the numeric part and sort the messages numerically.
  3. Remove the header portion from each message.
  4. Concatenate the resulting message bodies and write them to an output file.
  5. Print a summary showing the total messages found and, if using a header filter, any missing expected headers.

If no header filter is specified, the script concatenates all extracted Text fields and writes them to the output file.
"""

import argparse
import re
import sys

def extract_text_fields(file_content):
    """
    Extract all JSON objects' "Text" field from the log content.
    Uses a regex to search for the value of the "Text" key (which may span multiple lines).
    """
    pattern = re.compile(r'"Text":\s*"(.+?)"', re.DOTALL)
    return pattern.findall(file_content)

def main():
    parser = argparse.ArgumentParser(
        description="Sort Meshtastic messages by header numeric value, remove the headers, and write them to an output file."
    )
    parser.add_argument("file_path", help="Path to the input log file containing messages")
    parser.add_argument("--header", type=str, default=None,
                        help=("Header filter to use. Only messages whose Text field starts with "
                              "this header followed by digits and an exclamation mark (e.g. 'ad01!') "
                              "will be processed."))
    parser.add_argument("--output", type=str, default="compiled_messages.log",
                        help="Output file path for the concatenated messages (default: compiled_messages.log)")
    args = parser.parse_args()

    # Read the input file.
    try:
        with open(args.file_path, "r") as f:
            content = f.read()
    except Exception as e:
        sys.exit(f"Error reading file: {e}")

    # Extract all "Text" fields.
    texts = extract_text_fields(content)
    if not texts:
        print("No messages ('Text' fields) could be extracted from the file.")
        sys.exit(0)
    
    concatenated_output = ""
    
    if args.header:
        # Build a pattern to match messages starting with the header filter followed by digits and '!'
        header_pat = re.compile(r"^" + re.escape(args.header) + r"(\d+)!")
        matched = []
        for text in texts:
            stripped = text.strip()
            m = header_pat.match(stripped)
            if m:
                try:
                    num = int(m.group(1))
                except ValueError:
                    continue
                matched.append((num, stripped))
        if not matched:
            print("No messages matching the header filter were found.")
            sys.exit(0)
  
        # Sort messages by the numeric portion.
        matched.sort(key=lambda tup: tup[0])
        # Remove the header from each message. We do this by replacing the header pattern at the start with an empty string.
        cleaned_messages = [re.sub(r"^" + re.escape(args.header) + r"\d+!", "", msg, count=1) for (_, msg) in matched]
        concatenated_output = "\n".join(cleaned_messages)

        total_found = len(cleaned_messages)
        # Determine the digit width from the first match.
        first_match = header_pat.match(matched[0][1])
        width = len(first_match.group(1)) if first_match else 0
        max_num = max(num for num, _ in matched)
        expected = set(range(1, max_num + 1))
        found = set(num for num, _ in matched)
        missing = sorted(list(expected - found))
        
        summary_lines = [
            "----- Summary -----",
            f"Total messages found (after filtering): {total_found}",
            f"Maximum header found: {args.header}{max_num:0{width}d}!"
        ]
        if missing:
            missing_formatted = ", ".join(f"{args.header}{n:0{width}d}!" for n in missing)
            summary_lines.append(f"Missing headers: {missing_formatted}")
        else:
            summary_lines.append("No missing headers found.")
    else:
        # No header filter provided; simply concatenate all extracted text fields.
        concatenated_output = "\n".join(texts)
        summary_lines = [
            "----- Summary -----",
            f"Total messages found: {len(texts)}"
        ]
    
    # Write the concatenated output to the specified output file.
    try:
        with open(args.output, "w") as outfile:
            outfile.write(concatenated_output)
    except Exception as e:
        sys.exit(f"Error writing output file: {e}")

    # Print summary to terminal.
    print("\n".join(summary_lines))
    print(f"\nCompiled messages written to: {args.output}")

if __name__ == "__main__":
    main()
