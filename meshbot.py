#!/usr/bin/env python3
"""
Production‑Ready Meshbot Unified Script

This script consolidates three modes of operation into one production‑quality utility:
  • Bot Mode: A persistent bot that listens for Meshtastic messages and responds to commands.
  • Sender Mode: Processes an image and/or sends file content (in chunks) via a persistent Meshtastic connection.
  • Receiver Mode: Asynchronously collects messages, assembles Base64 payloads, decodes/decompresses them,
                   and optionally uploads the resulting file using rsync.

Usage:
  python3 meshbot.py <mode> [options]

Modes:
  bot       - Run Bot mode.
  sender    - Run Sender mode.
  receiver  - Run Receiver mode.

For detailed help on each mode, run:
  python3 meshbot.py <mode> --help
"""

import argparse
import asyncio
import base64
import gzip
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import glob
import random
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs

import requests
import zopfli.gzip

# Attempt to import Meshtastic libraries.
try:
    from meshtastic.tcp_interface import TCPInterface
except ImportError:
    TCPInterface = None
try:
    from meshtastic.serial_interface import SerialInterface
except ImportError:
    SerialInterface = None
try:
    from pubsub import pub
except ImportError:
    pub = None

# ---------------------------------------------------------------------------
# Logging and Common Utility Functions
# ---------------------------------------------------------------------------
def configure_logging(debug_mode: bool) -> None:
    """
    Configures logging for the application.
    
    Args:
      debug_mode: If True, set logging to DEBUG; otherwise INFO.
    """
    log_level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("debug_messages.log")
        ]
    )

logger = logging.getLogger("Meshbot")

def print_table(title: str, items: list) -> None:
    """
    Prints an ASCII table with the given title and key-value tuples.
    
    Args:
      title: Title of the table.
      items: List of (key, value) tuples.
    """
    table_width1 = 30
    table_width2 = 50
    separator = "+" + "-" * table_width1 + "+" + "-" * table_width2 + "+"
    title_line = "| {:^{w1}} | {:^{w2}} |".format(title, "", w1=table_width1 - 2, w2=table_width2 - 2)
    print(separator)
    print(title_line)
    print(separator)
    for key, value in items:
        print("| {:<{w1}} | {:<{w2}} |".format(key, str(value), w1=table_width1 - 2, w2=table_width2 - 2))
    print(separator)

# ---------------------------------------------------------------------------
# System Information Utilities (Common to all modes)
# ---------------------------------------------------------------------------
def get_system_info() -> str:
    """Returns basic system information."""
    import platform
    uname = platform.uname()
    info = f"System: {uname.system} {uname.node} {uname.release}"
    try:
        loadavg = os.getloadavg()
        info += f" | Load: {loadavg[0]:.2f}, {loadavg[1]:.2f}, {loadavg[2]:.2f}"
    except Exception:
        info += " | Load: N/A"
    return info

def get_general_sysinfo() -> str:
    """Returns a detailed system info summary."""
    import platform
    uname = platform.uname()
    return (
        f"General System Info:\n"
        f"  System:    {uname.system}\n"
        f"  Node:      {uname.node}\n"
        f"  Release:   {uname.release}\n"
        f"  Version:   {uname.version}\n"
        f"  Machine:   {uname.machine}\n"
        f"  Processor: {uname.processor}"
    )

def get_disk_info() -> str:
    """Returns disk usage statistics."""
    try:
        total, used, free = shutil.disk_usage("/")
        return (f"Disk Usage (/): Total: {total/(1024**3):.2f} GB, "
                f"Used: {used/(1024**3):.2f} GB, Free: {free/(1024**3):.2f} GB")
    except Exception as e:
        return f"Error retrieving disk info: {e}"

def get_cpu_temp() -> str:
    """Returns CPU temperature if available."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = int(f.read().strip()) / 1000.0
        return f"CPU Temperature: {temp:.1f}°C"
    except Exception as e:
        return f"Error reading CPU temperature: {e}"

def get_ip_address() -> str:
    """Returns the primary IP address of the host."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"IP Address: {ip}"
    except Exception as e:
        return f"Error determining IP address: {e}"

def get_mem_info() -> str:
    """Returns memory usage information (in MB)."""
    try:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) > 1:
                    meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
        total = meminfo.get("MemTotal", 0) / 1024
        free = meminfo.get("MemFree", 0) / 1024
        avail = meminfo.get("MemAvailable", free) / 1024
        return f"Memory (MB): Total: {total:.0f}, Free: {free:.0f}, Available: {avail:.0f}"
    except Exception as e:
        return f"Error retrieving memory info: {e}"

def get_random_joke() -> str:
    """Returns a random joke."""
    jokes = [
        "Why do programmers prefer dark mode? Because light attracts bugs!",
        "I would tell you a UDP joke, but you might not get it.",
        "Why did the LoRa device get confused? It lost its connection!",
        "I tried connecting my node to the internet, but it got lost in the clouds!"
    ]
    return random.choice(jokes)

def get_help_text() -> str:
    """Returns a help text listing available commands."""
    return (
        "Available commands:\n"
        "  hi!        - Greets you back\n"
        "  cpu!       - Basic system/CPU info\n"
        "  status!    - Detailed node status\n"
        "  sysinfo!   - General system info\n"
        "  df!        - Disk usage info\n"
        "  temp!      - CPU temperature\n"
        "  ip!        - IP address\n"
        "  mem!       - Memory info\n"
        "  joke!      - Tell a joke\n"
        "  help!      - Show help text\n"
        "  ping!      - Reply with pong!\n"
        "  time!      - Current local time\n"
        "  fortune!   - Random fortune\n"
        "  dmesg!     - Kernel messages (last 5 lines)\n"
        "  signal!    - Nearby node signals\n"
        "  sendimage! - Process and send image via query-string parameters\n"
    )

def get_current_time() -> str:
    """Returns the current local time as a formatted string."""
    return f"Current Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"

def get_random_fortune() -> str:
    """Returns a random fortune."""
    fortunes = [
        "You will have a pleasant surprise today!",
        "A thrilling time is in your near future.",
        "Fortune favors the brave.",
        "Unexpected bugs ahead!",
        "Your code will run without errors today!"
    ]
    return random.choice(fortunes)

def get_dmesg_info() -> str:
    """Returns the last 5 lines of the kernel log (truncated if needed)."""
    try:
        output = subprocess.check_output("sudo dmesg | tail -n 5", shell=True, universal_newlines=True)
        return f"Kernel messages:\n{output[:200] + '...' if len(output) > 200 else output}"
    except Exception as e:
        return f"Error retrieving dmesg: {e}"

def get_signal_info(interface) -> str:
    """Returns information about nearby nodes with active signal."""
    if not interface or not hasattr(interface, "nodes") or not interface.nodes:
        return "No signal data available."
    active = []
    for node_id, data in interface.nodes.items():
        try:
            float(data.get("rssi", -999))
            active.append((node_id, data))
        except Exception:
            continue
    if not active:
        return "No active signals."
    active.sort(key=lambda x: float(x[1].get("rssi", -999)), reverse=True)
    lines = ["Nearby nodes with active signal:"]
    for nid, data in active[:5]:
        lines.append(f"Node {nid}: RSSI {data.get('rssi','N/A')}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Connection Manager and Signal Handling (Shared)
# ---------------------------------------------------------------------------
class MeshtasticConnectionManager:
    """
    Manages a Meshtastic connection (TCP or Serial) in a unified fashion.
    """
    def __init__(self, tcp_host: str = "localhost", connection: str = "tcp"):
        self.tcp_host = tcp_host
        self.connection_type = connection
        self.interface = None

    def open_connection(self, on_receive_callback=None):
        """
        Opens a connection using the specified type and registers a callback.
        
        Args:
          on_receive_callback: Function to call on receiving messages.
          
        Returns:
          The Meshtastic interface object.
        """
        if self.connection_type == "tcp":
            if TCPInterface is None:
                logger.error("TCPInterface not available!")
                sys.exit(1)
            try:
                self.interface = TCPInterface(hostname=self.tcp_host)
                if pub and on_receive_callback:
                    pub.subscribe(on_receive_callback, "meshtastic.receive")
                logger.info("Connected via TCP on %s", self.tcp_host)
            except Exception as e:
                logger.error("Error establishing TCP connection: %s", e)
                sys.exit(1)
        elif self.connection_type == "serial":
            if SerialInterface is None:
                logger.error("SerialInterface not available!")
                sys.exit(1)
            try:
                self.interface = SerialInterface()
                if on_receive_callback:
                    self.interface.onReceive = on_receive_callback
                logger.info("Connected via Serial.")
            except Exception as e:
                logger.error("Error establishing Serial connection: %s", e)
                sys.exit(1)
        else:
            logger.error("Unknown connection type: %s", self.connection_type)
            sys.exit(1)
        return self.interface

    def close_connection(self):
        if self.interface:
            try:
                self.interface.close()
                logger.info("Connection closed.")
            except Exception as e:
                logger.error("Error closing connection: %s", e)

def setup_signal_handlers(obj) -> None:
    """
    Sets up signal handling for graceful shutdown.
    The passed object is expected to have either a 'running' attribute or a 'close_connection' method.
    """
    def handler(sig, frame):
        logger.info("CTRL+C detected, shutting down...")
        if hasattr(obj, "running"):
            obj.running = False
        if hasattr(obj, "close_connection"):
            obj.close_connection()
        sys.exit(0)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

# ---------------------------------------------------------------------------
# File Upload Helper (shared by Sender and Receiver)
# ---------------------------------------------------------------------------
def upload_file(file_path: str, remote_target: str, ssh_key: str) -> None:
    """
    Uploads the specified file to a remote destination with a timestamped filename.
    Uses rsync with low CPU priority.
    """
    remote_path = f"{remote_target.rstrip('/')}/{time.strftime('%Y%m%d%H%M%S')}-restored.jpg"
    cmd = ["nice", "-n", "10", "rsync", "-vz", "-e", f"ssh -i {ssh_key}", file_path, remote_path]
    try:
        subprocess.check_call(cmd)
        logger.info("File uploaded to %s", remote_path)
    except subprocess.CalledProcessError as e:
        logger.error("Upload failed: %s", e)
        sys.exit(1)
# ---------------------------------------------------------------------------
# MODE 1: Bot Mode Implementation
# ---------------------------------------------------------------------------
class BotMode:
    def __init__(self, args):
        self.args = args
        self.node_id = args.node_id if hasattr(args, "node_id") else None
        self.channel_index = args.channel_index if hasattr(args, "channel_index") else None
        self.conn_manager = MeshtasticConnectionManager(tcp_host=args.tcp_host, connection="tcp")
        self.start_time = time.time()

    def on_receive(self, packet, interface=None):
        sender = packet.get("fromId", "")
        # Filter based on node ID if specified.
        if self.node_id and sender.lstrip("!") != self.node_id:
            logger.info("Ignoring message from node %s (expected %s).", sender, self.node_id)
            return

        # Retrieve and clean the text message.
        text = (packet.get("decoded", {}).get("text", "") or packet.get("text", "")).strip().lower()
        if not text:
            return
        logger.info("Received message from node %s: %s", sender, text)

        # Process commands and respond accordingly.
        if text == "hi!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText("well hai!")
            return
        elif text == "cpu!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_system_info())
            return
        elif text == "sysinfo!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_general_sysinfo())
            return
        elif text == "df!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_disk_info())
            return
        elif text == "temp!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_cpu_temp())
            return
        elif text == "ip!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_ip_address())
            return
        elif text == "mem!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_mem_info())
            return
        elif text == "joke!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_random_joke())
            return
        elif text == "help!":
            if self.conn_manager.interface:
                for line in get_help_text().splitlines():
                    self.conn_manager.interface.sendText(line)
            return
        elif text == "ping!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText("pong!")
            return
        elif text == "time!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_current_time())
            return
        elif text == "fortune!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_random_fortune())
            return
        elif text == "dmesg!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_dmesg_info())
            return
        elif text == "signal!":
            if self.conn_manager.interface:
                self.conn_manager.interface.sendText(get_signal_info(self.conn_manager.interface))
            return
        elif text.startswith("sendimage!"):
            # Delegate processing to sender mode.
            query_string = text[len("sendimage!"):].strip()
            cmd = [
                "python3", sys.argv[0], "sender",
                "--mode", "all",
                "--sender_node_id", self.node_id,
                "--header", query_string
            ]
            logger.info("Executing sendimage! command: %s", " ".join(cmd))
            self.conn_manager.close_connection()
            time.sleep(5)
            subprocess.run(cmd, check=True)
            return
        else:
            logger.info("No matching command for message: %s", text)

    def run(self):
        self.conn_manager.open_connection(on_receive_callback=self.on_receive)
        setup_signal_handlers(self)
        logger.info("Bot mode running. Listening for messages...")
        try:
            while True:
                if self.conn_manager.interface is None:
                    logger.info("Re-establishing connection...")
                    self.conn_manager.open_connection(on_receive_callback=self.on_receive)
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received in Bot mode.")
        finally:
            self.conn_manager.close_connection()

def run_bot_mode(args):
    bot = BotMode(args)
    bot.run()
# ---------------------------------------------------------------------------
# MODE 2: Sender Mode Implementation (Production)
# ---------------------------------------------------------------------------
# Constants for sender mode.
DEFAULT_MAX_RETRIES = 10
DEFAULT_RETRY_DELAY = 1      # in seconds
DEFAULT_SLEEP_DELAY = 1.0    # in seconds

class PersistentMeshtasticSender:
    """
    Uses a persistent Meshtastic connection to send file content in fixed-size chunks.
    Optionally, a header is prepended to each chunk for identification/reassembly.
    """
    def __init__(self, file_path: Path, chunk_size: int, ch_index: int, dest: str,
                 connection: str, max_retries: int = DEFAULT_MAX_RETRIES, 
                 retry_delay: int = DEFAULT_RETRY_DELAY, header_template: str = None,
                 use_ack: bool = False, sleep_delay: float = DEFAULT_SLEEP_DELAY):
        self.file_path = file_path
        self.chunk_size = chunk_size
        self.ch_index = ch_index
        self.dest = dest
        self.connection = connection.lower()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.header_template = header_template
        self.use_ack = use_ack
        self.sleep_delay = sleep_delay
        self.interface = None

    def read_file(self) -> str:
        try:
            return self.file_path.read_text()
        except Exception as e:
            logger.error("Error reading file '%s': %s", self.file_path, e)
            sys.exit(1)

    def get_file_size(self) -> int:
        return self.file_path.stat().st_size

    def chunk_content(self, content: str) -> list:
        return [content[i:i+self.chunk_size] for i in range(0, len(content), self.chunk_size)]

    def generate_header(self, index: int, total_chunks: int) -> str:
        if not self.header_template:
            return ""
        if '#' in self.header_template:
            pattern = re.compile(r"(#+)")
            match = pattern.search(self.header_template)
            if match:
                width = len(match.group(0))
                header = pattern.sub(f"{index:0{width}d}", self.header_template, count=1)
                return header if header.endswith("!") else header + "!"
            else:
                return f"{self.header_template}{index}!"
        else:
            width = len(str(total_chunks))
            return f"{self.header_template}{index:0{width}d}!"

    def open_connection(self):
        conn_mgr = MeshtasticConnectionManager(tcp_host="localhost", connection=self.connection)
        self.interface = conn_mgr.open_connection()
        return self.interface

    def close_connection(self):
        if self.interface:
            try:
                self.interface.close()
            except Exception as e:
                logger.error("Error closing sender connection: %s", e)

    def send_chunk(self, message: str, chunk_index: int, total_chunks: int) -> int:
        header = self.generate_header(chunk_index, total_chunks) if self.header_template else ""
        full_message = header + message
        attempt = 0
        while attempt < self.max_retries:
            try:
                self.interface.sendText(full_message, wantAck=self.use_ack)
                logger.info("Sent chunk %d/%d with header '%s' (Attempt %d)", 
                            chunk_index, total_chunks, header, attempt+1)
                return attempt
            except Exception as e:
                attempt += 1
                logger.warning("Retry %d/%d for chunk %d due to error: %s", 
                               attempt, self.max_retries, chunk_index, e)
                time.sleep(self.retry_delay)
                if attempt == self.max_retries:
                    logger.error("Aborting after %d retries for chunk %d.", 
                                 self.max_retries, chunk_index)
                    sys.exit(1)
        return attempt

    def send_all_chunks(self):
        content = self.read_file()
        chunks = self.chunk_content(content)
        total_chunks = len(chunks)
        total_failures = 0
        for i, chunk in enumerate(chunks, start=1):
            total_failures += self.send_chunk(chunk, i, total_chunks)
            time.sleep(self.sleep_delay)
        return total_chunks, total_failures

def setup_sender_signal_handlers(sender: PersistentMeshtasticSender) -> None:
    setup_signal_handlers(sender)

def run_sender_mode(args) -> None:
    if args.mode == "process":
        logger.info("Running image processing pipeline...")
        summary = optimize_compress_zip_base64encode_jpg(
            quality=args.quality,
            resize=args.resize,
            snapshot_url="http://localhost:8080/0/action/snapshot",
            output_file=args.output
        )
        for k, v in summary.items():
            logger.info("%s: %s", k, v)
        if args.upload:
            logger.info("Uploading processed image file...")
            upload_file(args.output, args.remote_target, args.ssh_key)
    else:
        if args.mode == "send" and not args.file_path:
            logger.error("--file_path is required for send mode.")
            sys.exit(1)
        file_path = Path(args.file_path) if args.file_path else Path(args.output)
        sender = PersistentMeshtasticSender(
            file_path=file_path,
            chunk_size=args.chunk_size,
            ch_index=args.ch_index,
            dest=args.dest,
            connection=args.connection,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
            header_template=args.header,
            use_ack=args.ack,
            sleep_delay=args.sleep_delay
        )
        setup_sender_signal_handlers(sender)
        start_time = time.time()
        sender.open_connection()
        total_chunks, total_failures = sender.send_all_chunks()
        sender.close_connection()
        elapsed = time.time() - start_time
        file_size = sender.get_file_size()
        summary_items = [
            ("Start Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))),
            ("Time Elapsed", time.strftime("%H:%M:%S", time.gmtime(elapsed))),
            ("Total Chunks Sent", total_chunks),
            ("File Size", f"{file_size} bytes")
        ]
        print_table("Sender Execution Summary", summary_items)
# ---------------------------------------------------------------------------
# MODE 3: Receiver Mode Implementation (Production)
# ---------------------------------------------------------------------------
class MeshtasticReceiver:
    def __init__(self, args):
        self.args = args
        self.received_messages = {}  # Mapping: header number -> full message text
        self.duplicate_count = 0
        self.combined_messages = []  # List for holding payloads (after header removal)
        self.state_lock = Lock()
        self.running = True
        self.iface = None
        self.last_message_time = time.time()
        self.highest_header = 0
        self.start_time = time.time()
        self.header_digit_pattern = re.compile(r"\d+")
        self.last_progress_time = time.time()

    def print_startup_summary(self) -> None:
        params = [
            ("run_time (min)", self.args.run_time),
            ("sender_node_id", self.args.sender_node_id),
            ("header", self.args.header),
            ("output", self.args.output),
            ("remote_target", self.args.remote_target),
            ("ssh_key", self.args.ssh_key),
            ("poll_interval (sec)", self.args.poll_interval),
            ("inactivity_timeout (sec)", self.args.inactivity_timeout),
            ("connection", self.args.connection),
            ("tcp_host", self.args.tcp_host),
            ("process_image", self.args.process_image),
            ("upload", self.args.upload),
            ("debug", self.args.debug),
        ]
        print_table("Receiver Startup Summary", params)

    def print_performance_summary(self, total_runtime: float, total_msgs: int,
                                    missing_msgs: int, file_size) -> None:
        stats = [
            ("Total Runtime (sec)", f"{total_runtime:.2f}"),
            ("Total Unique Messages", total_msgs),
            ("Highest Header Processed", self.highest_header),
            ("Duplicate Messages", self.duplicate_count),
            ("Estimated Missing Msgs", missing_msgs),
            ("Transferred File Size (bytes)", file_size),
        ]
        print_table("Receiver Performance Summary", stats)

    def on_receive(self, packet, interface=None) -> None:
        """
        Processes an incoming message packet.
        Filters by sender_node_id and expected header.
        Extracts the numeric header and stores the message.
        """
        try:
            raw_sender = packet.get("fromId")
            if not raw_sender or raw_sender.lstrip("!") != self.args.sender_node_id:
                logger.debug("Ignored message from sender '%s' (expected %s).", raw_sender, self.args.sender_node_id)
                return

            text = (packet.get("decoded", {}).get("text", "").strip() or
                    packet.get("text", "").strip())
            if not text:
                logger.debug("Ignored empty message.")
                return

            if not text.startswith(self.args.header):
                logger.debug("Message does not start with expected header '%s': %s", self.args.header, text)
                return

            # Remove header: assume everything up to and including the first "!" is the header.
            header_part, sep, _ = text.partition("!")
            if not sep:
                logger.debug("Message missing header delimiter: %s", text)
                return

            match = self.header_digit_pattern.search(header_part)
            if match:
                header_num = int(match.group())
            else:
                logger.debug("Could not extract header number from '%s' in message: %s", header_part, text)
                return

            with self.state_lock:
                if header_num in self.received_messages:
                    self.duplicate_count += 1
                    logger.debug("Duplicate message with header %d; ignoring.", header_num)
                else:
                    self.received_messages[header_num] = text
                    if header_num > self.highest_header:
                        self.highest_header = header_num
                        logger.info("Updated highest header to %d.", self.highest_header)
                    self.last_message_time = time.time()
        except Exception as e:
            logger.error("Exception in on_receive: %s", e)

    def connect_meshtastic(self):
        """
        Uses the shared connection manager to open a connection and register the on_receive callback.
        """
        conn_mgr = MeshtasticConnectionManager(tcp_host=self.args.tcp_host, connection=self.args.connection)
        self.iface = conn_mgr.open_connection(on_receive_callback=self.on_receive)
        return self.iface

    def combine_messages(self) -> None:
        """
        Combines the stored messages into a single payload string.
        Assumes that header and payload are separated by the first "!".
        """
        with self.state_lock:
            sorted_items = sorted(self.received_messages.items())
            # Remove header portion from each message.
            self.combined_messages = [
                msg.split("!", 1)[1] if "!" in msg else msg for _, msg in sorted_items
            ]

    def decode_and_save_image(self) -> None:
        """
        Decodes the concatenated Base64 data and decompresses the gzip data.
        Saves the resulting image to the output file.
        """
        logger.info("Decoding Base64 data and decompressing...")
        combined_data = "".join(self.combined_messages)
        try:
            padded = combined_data.ljust(((len(combined_data) + 3) // 4) * 4, "=")
            decoded = base64.b64decode(padded)
            decompressed = gzip.decompress(decoded)
            with open(self.args.output, "wb") as f:
                f.write(decompressed)
            logger.info("Image saved to %s", self.args.output)
        except Exception as e:
            logger.error("Error during decoding/decompression: %s", e)
            sys.exit(1)

    def upload_image(self) -> None:
        """
        Uploads the processed output file to a remote destination using rsync with lowered CPU priority.
        Retries up to three times.
        """
        remote_path = f"{self.args.remote_target.rstrip('/')}/{time.strftime('%Y%m%d%H%M%S')}-restored.jpg"
        cmd = ["nice", "-n", "10", "rsync", "-vz", "-e", f"ssh -i {self.args.ssh_key}", self.args.output, remote_path]
        for attempt in range(1, 4):
            try:
                subprocess.check_call(cmd)
                logger.info("Image uploaded to %s", remote_path)
                return
            except subprocess.CalledProcessError as e:
                logger.error("Upload attempt %d failed: %s", attempt, e)
                time.sleep(3)
        logger.error("Image upload failed after 3 attempts.")
        sys.exit(1)

    async def run(self) -> None:
        """
        Main asynchronous loop that collects messages until the run_time expires or an inactivity timeout occurs.
        Then processes and optionally uploads the received data.
        """
        self.connect_meshtastic()
        end_time = self.start_time + self.args.run_time * 60
        logger.info("Receiver mode: entering main collection loop...")
        while self.running and time.time() < end_time:
            now = time.time()
            if now - self.last_message_time > self.args.inactivity_timeout:
                logger.info("Inactivity timeout reached; stopping collection.")
                self.running = False
                break
            if now - self.last_progress_time >= self.args.poll_interval:
                with self.state_lock:
                    total_msgs = len(self.received_messages)
                    current_highest = self.highest_header
                remaining = end_time - now
                logger.info("Progress: %d messages, highest header %d, time remaining: %.1f sec",
                            total_msgs, current_highest, remaining)
                self.last_progress_time = now
            await asyncio.sleep(0.5)

        # Close the connection gracefully.
        if self.iface:
            try:
                self.iface.close()
            except Exception as e:
                logger.debug("Error closing interface: %s", e)

        # Process the collected messages.
        self.combine_messages()
        if self.args.process_image:
            self.decode_and_save_image()
        else:
            logger.info("Skipping image processing (--process_image flag not set).")
        if self.args.upload:
            self.upload_image()
        else:
            logger.info("Skipping file upload (--upload flag not set).")

        total_runtime = time.time() - self.start_time
        with self.state_lock:
            total_msgs = len(self.received_messages)
        missing_msgs = self.highest_header - total_msgs if self.highest_header > total_msgs else 0
        file_size = os.path.getsize(self.args.output) if self.args.process_image and os.path.exists(self.args.output) else "N/A"
        self.print_performance_summary(total_runtime, total_msgs, missing_msgs, file_size)

def setup_receiver_signal_handlers(receiver: MeshtasticReceiver) -> None:
    setup_signal_handlers(receiver)

def run_receiver_mode(args) -> None:
    receiver = MeshtasticReceiver(args)
    receiver.print_startup_summary()
    setup_receiver_signal_handlers(receiver)
    try:
        asyncio.run(receiver.run())
    except Exception as e:
        logger.error("Fatal error in receiver mode: %s", e)
        sys.exit(1)
# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Meshbot Unified – Run in bot, sender, or receiver mode."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True, help="Operating mode")

    # ----- Bot Mode Parser -----
    bot_parser = subparsers.add_parser("bot", help="Run Bot mode")
    bot_parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost)")
    bot_parser.add_argument("--channel_index", type=int, default=0, help="Channel index for filtering (use -1 to disable)")
    bot_parser.add_argument("--node_id", type=str, default=None, help="Sender node ID to filter messages")
    bot_parser.add_argument("--debug", action="store_true", help="Enable debug mode for detailed logging")

    # ----- Sender Mode Parser -----
    sender_parser = subparsers.add_parser("sender", help="Run Sender mode")
    sender_parser.add_argument("--mode", choices=["send", "process", "all"], default="all",
                               help="Mode to run: 'process' to only process an image, 'send' to send file content, or 'all'")
    sender_parser.add_argument("--sender_node_id", required=True, help="Sender node ID (for reference)")
    sender_parser.add_argument("--header", type=str, default="pn", help="Header template (use '#' for digit placeholders)")
    # Image processing parameters.
    sender_parser.add_argument("--quality", type=int, default=75, help="JPEG quality factor for optimization")
    sender_parser.add_argument("--resize", type=str, default="800x600", help="Resize dimensions (e.g., 800x600)")
    sender_parser.add_argument("--output", type=str, default="base64_image.gz", help="Output file for image processing")
    # Upload parameters.
    sender_parser.add_argument("--remote_target", type=str, help="Remote path for file upload (if --upload is set)")
    sender_parser.add_argument("--ssh_key", type=str, help="SSH identity file for rsync (if --upload is set)")
    sender_parser.add_argument("--poll_interval", type=int, default=10, help="Poll interval in seconds")
    sender_parser.add_argument("--inactivity_timeout", type=int, default=60, help="Inactivity timeout in seconds")
    sender_parser.add_argument("--connection", type=str, choices=["tcp", "serial"], default="tcp", help="Connection mode")
    sender_parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost)")
    sender_parser.add_argument("--process_image", action="store_true", help="Run the image processing pipeline")
    sender_parser.add_argument("--upload", action="store_true", help="Upload the processed image file using rsync")
    # Sending pipeline parameters.
    sender_parser.add_argument("--file_path", type=str, help="Path to text file to send (if not provided, defaults to output file)")
    sender_parser.add_argument("--chunk_size", type=int, default=200, help="Maximum length of each chunk")
    sender_parser.add_argument("--ch_index", type=int, default=1, help="Starting chunk index (default: 1)")
    sender_parser.add_argument("--dest", type=str, default="!47a78d36", help="Destination token for Meshtastic send")
    sender_parser.add_argument("--ack", action="store_true", help="Enable ACK mode for sending")
    sender_parser.add_argument("--max_retries", type=int, default=DEFAULT_MAX_RETRIES, help="Maximum retries per chunk")
    sender_parser.add_argument("--retry_delay", type=int, default=DEFAULT_RETRY_DELAY, help="Delay (s) between retries")
    sender_parser.add_argument("--sleep_delay", type=float, default=DEFAULT_SLEEP_DELAY, help="Sleep delay (s) between chunks")
    sender_parser.add_argument("--debug", action="store_true", help="Enable debug mode for detailed logging")

    # ----- Receiver Mode Parser -----
    receiver_parser = subparsers.add_parser("receiver", help="Run Receiver mode")
    receiver_parser.add_argument("--run_time", type=int, required=True, help="Run time (in minutes)")
    receiver_parser.add_argument("--sender_node_id", required=True, help="Sender node ID to filter messages")
    receiver_parser.add_argument("--header", type=str, default="pn", help="Expected message header prefix")
    receiver_parser.add_argument("--output", type=str, default="restored.jpg", help="Output image file")
    receiver_parser.add_argument("--remote_target", type=str, required=True, help="Remote path for image upload")
    receiver_parser.add_argument("--ssh_key", type=str, required=True, help="SSH identity file for rsync")
    receiver_parser.add_argument("--poll_interval", type=int, default=10, help="Poll interval in seconds")
    receiver_parser.add_argument("--inactivity_timeout", type=int, default=60, help="Inactivity timeout in seconds")
    receiver_parser.add_argument("--connection", type=str, choices=["tcp", "serial"], required=True, help="Connection mode")
    receiver_parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost)")
    receiver_parser.add_argument("--debug", action="store_true", help="Enable debug mode for detailed logging")
    receiver_parser.add_argument("--process_image", action="store_true", help="Process Base64 data as an image")
    receiver_parser.add_argument("--upload", action="store_true", help="Upload the processed image file using rsync")

    args = parser.parse_args()
    configure_logging(args.debug)

    if args.mode == "bot":
        run_bot_mode(args)
    elif args.mode == "sender":
        run_sender_mode(args)
    elif args.mode == "receiver":
        run_receiver_mode(args)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
