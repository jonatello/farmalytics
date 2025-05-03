#!/usr/bin/env python3
"""
meshtastic_input.py

This script reads a log file containing Meshtastic messages logged as JSON.
It extracts the "Text" field from each JSON object.
If a header filter is specified via --header, the script will:
  1. Filter messages whose Text field starts with the given header followed by a numeric part and an exclamation mark.
  2. Extract that numeric part, sort the messages numerically, and then remove the header portion.
  3. If --progress-only is set, only report progress (i.e. the fraction of expected messages received)
     and exit with code 0 if 100% of the headers are present, or with 1 otherwise.
  4. Otherwise, concatenate the resulting message bodies and, if an --output file is specified, write them.
  5. In either case, print a summary showing:
       - Total messages found (after filtering)
       - Expected total (inferred from the maximum header number)
       - Progress (count and percentage)
       - Any missing headers for troubleshooting.
If no header filter is specified, the script simply concatenates all extracted Text fields.
"""

import argparse
import re
import sys

def extract_text_fields(file_content):
    pattern = re.compile(r'"Text":\s*"(.+?)"', re.DOTALL)
    return pattern.findall(file_content)

def main():
    parser = argparse.ArgumentParser(
        description=("Sort Meshtastic messages by header numeric value, remove the header in the output, "
                     "and report progress based on expected total (from max header).")
    )
    parser.add_argument("file_path", help="Path to the input log file containing messages")
    parser.add_argument("--header", type=str, default=None,
                        help=("Header filter to use. Only messages whose Text field starts with "
                              "this header followed by digits and an exclamation mark will be processed "
                              "(e.g. '--header pb' matches messages like 'pb01!', 'pb03!', etc.)"))
    parser.add_argument("--output", type=str, default="",
                        help="(Optional) Output file path for the concatenated message bodies (without header).")
    parser.add_argument("--progress-only", action="store_true",
                        help="If set, only report progress (messages received vs. expected) and do not output the concatenated result.")
    args = parser.parse_args()

    try:
        with open(args.file_path, "r") as f:
            content = f.read()
    except Exception as e:
        sys.exit(f"Error reading file: {e}")

    texts = extract_text_fields(content)
    if not texts:
        print("No messages could be extracted from the file.")
        sys.exit(0)

    if args.header:
        header_pat = re.compile(r"^" + re.escape(args.header) + r"(\d+)!")
        matched = []
        for text in texts:
            txt = text.strip()
            m = header_pat.match(txt)
            if m:
                try:
                    num = int(m.group(1))
                except ValueError:
                    continue
                matched.append((num, txt))
        if not matched:
            print("No messages matching the header filter were found.")
            sys.exit(0)

        matched.sort(key=lambda tup: tup[0])
        total_found = len(matched)
        max_num = max(num for num, _ in matched)
        progress = (total_found / max_num) * 100 if max_num > 0 else 0

        # If progress-only, output just the progress and exit.
        if args.progress_only:
            print(f"Progress: {total_found} / {max_num} ({progress:.1f}%)")
            sys.exit(0 if total_found == max_num else 1)
        else:
            # Remove header from each message.
            cleaned_messages = [re.sub(r"^" + re.escape(args.header) + r"\d+!", "", msg, count=1).strip()
                                for _, msg in matched]
            output_text = "\n".join(cleaned_messages)
            if args.output:
                try:
                    with open(args.output, "w") as out_file:
                        out_file.write(output_text)
                except Exception as e:
                    sys.exit(f"Error writing output file: {e}")
            # Print complete summary.
            print("----- Summary -----")
            print(f"Total messages received (after filtering): {total_found}")
            print(f"Expected messages (inferred from max header): {args.header}{max_num}!")
            print(f"Progress: {total_found} / {max_num} ({progress:.1f}%)")
            if total_found != max_num:
                expected = set(range(1, max_num + 1))
                found = set(num for num, _ in matched)
                missing = sorted(expected - found)
                if missing:
                    missing_formatted = ", ".join(f"{args.header}{n}!" for n in missing)
                    print(f"Missing headers: {missing_formatted}")
                else:
                    print("No missing headers.")
    else:
        # When no header is provided, simply concatenate.
        output_text = "\n".join(texts)
        if args.output:
            try:
                with open(args.output, "w") as out_file:
                    out_file.write(output_text)
            except Exception as e:
                sys.exit(f"Error writing output file: {e}")
        print("----- Summary -----")
        print(f"Total messages found: {len(texts)}")

if __name__ == "__main__":
    main()
