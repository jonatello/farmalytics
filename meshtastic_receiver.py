#!/usr/bin/env python3
"""
meshtastic_receiver.py - Meshtastic Receiver & Processor

This script:
  - Encapsulates all functionality in the MeshtasticProcessor class.
  - Uses an asynchronous main loop (via asyncio) to avoid busy-waiting.
  - Consolidates ASCII table printing into a single helper (print_table()).
  - Filters incoming messages based on the sender_node_id and a message header.
  - Combines Base64 payloads from messages (after stripping off everything up to
    and including the first "!" character).
  - If the --process_image flag is set, decodes and decompresses the combined Base64
    data and writes an image file.
  - If the --upload flag is set, uploads the processed file using rsync (with lowered
    CPU priority).
  - Displays a performance summary (including file size transferred, if applicable)
    at the end.

Usage:
  python3 meshtastic_receiver.py --run_time <minutes> --sender_node_id <id> --header <prefix> \
    --output restored.jpg --remote_target <remote_path> --ssh_key <path> --connection tcp \
    --tcp_host localhost [--poll_interval 10] [--inactivity_timeout 60] [--process_image] [--upload] [--debug]

Note:
  sender_node_id is the original node identifier used for filtering messages.
  The --process_image flag tells the script that the Base64 data is an image and that
  image-specific post-processing should occur. The --upload flag tells the script to
  attempt file upload after processing.
"""
