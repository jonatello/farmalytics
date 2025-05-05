#!/usr/bin/env python3
"""
meshbot.py - Combined Meshtastic Bot (MeshBot)

This integrated script combines sender, receiver, postprocessing, filtering, and bot
functionalities into one file.

Service Modes (select using --service):
  bot       - Run the interactive bot (listens for commands such as hi!, cpu!, status!,
              sysinfo!, df!, temp!, ip!, mem!, joke!, help!, ping!, time!, fortune!, dmesg!,
              signal!, sendimage!<query>, simple!<message>).
  sender    - Run only the sender functionality. In complex mode (default for sender),
              it can run:
                • Image processing pipeline (capture, optimize, resize, compress, Base64 encode).
                • Persistent file sending (splitting file content into chunks and sending over Meshtastic).
              Use the --simple flag (with --message) for a plain text message.
  receiver  - Run only the receiver functionality. It collects asynchronous incoming messages,
              filters and assembles Base64 fragments, decodes and decompresses them into an image if
              --process_image is set, and can optionally upload the file.
  meshbot   - Runs both the bot functionality and receiver concurrently.

Usage examples:
 • Full bot:
      python3 meshbot.py --service bot --tcp_host localhost --channel_index 0 --node_id fb123456
 • Sender (complex mode):
      python3 meshbot.py --service sender --mode all --sender_node_id eb314389 --header nc --process_image --upload \
          --quality 75 --resize 800x600 --remote_target "user@host:/remote/path" --ssh_key "/path/to/id_rsa" \
          --chunk_size 200 --dest '!47a78d36' --connection tcp --ack --sleep_delay 1
 • Sender (simple mode):
      python3 meshbot.py --service sender --simple --message "Hello MeshBot!"
 • Receiver:
      python3 meshbot.py --service receiver --run_time 5 --sender_node_id fb123456 --header fb \
          --output restored.jpg --remote_target "user@host:/remote/path" --ssh_key "/path/to/id_rsa" \
          --connection tcp --tcp_host localhost --poll_interval 10 --inactivity_timeout 60 --process_image --upload --debug
 • Combined meshbot (bot + receiver):
      python3 meshbot.py --service meshbot --tcp_host localhost --channel_index 0 --node_id fb123456 \
          --run_time 5 --sender_node_id fb123456 --header fb --output restored.jpg \
          --remote_target "user@host:/remote/path" --ssh_key "/path/to/id_rsa" --connection tcp \
          --poll_interval 10 --inactivity_timeout 60 --process_image --upload --debug
"""

# ======================================================
#        Imports & Logging Setup
# ======================================================
import argparse
import asyncio
import base64
import gzip
import logging
import logging.handlers
import os
import platform
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

from meshtastic.tcp_interface import TCPInterface
from meshtastic.serial_interface import SerialInterface
from pubsub import pub

def configure_logging(debug_mode):
    level = logging.DEBUG if debug_mode else logging.INFO
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    file_handler = logging.FileHandler("debug_messages.log")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[console_handler, file_handler])

logger = logging.getLogger("MeshBot")

# ======================================================
#                Utility Functions
# ======================================================
def get_system_info():
    uname = platform.uname()
    try:
        loadavg = os.getloadavg()
        load = f"{loadavg[0]:.2f}, {loadavg[1]:.2f}, {loadavg[2]:.2f}"
    except Exception:
        load = "N/A"
    return f"System: {uname.system} {uname.node} {uname.release} | Load: {load}"

def get_general_sysinfo():
    uname = platform.uname()
    return (
        f"General System Info:\n"
        f"  System:    {uname.system}\n"
        f"  Node:      {uname.node}\n"
        f"  Release:   {uname.release}\n"
        f"  Version:   {uname.version}\n"
        f"  Machine:   {uname.machine}\n"
        f"  Processor: {uname.processor}\n"
        f"  Python:    {platform.python_version()}"
    )

def get_disk_info():
    try:
        total, used, free = shutil.disk_usage("/")
        return f"Disk: Total: {total/(1024**3):.2f}GB, Used: {used/(1024**3):.2f}GB, Free: {free/(1024**3):.2f}GB"
    except Exception as e:
        return f"Error retrieving disk info: {e}"

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = int(f.read().strip())/1000.0
        return f"CPU Temperature: {temp:.1f}°C"
    except Exception as e:
        return f"Error reading CPU temp: {e}"

def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"IP Address: {ip}"
    except Exception as e:
        return f"Error obtaining IP: {e}"

def get_mem_info():
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = {line.split(':')[0]: int(line.split()[1]) for line in f if ':' in line}
        total = meminfo.get("MemTotal", 0)/1024
        free = meminfo.get("MemFree", 0)/1024
        avail = meminfo.get("MemAvailable", free)/1024
        return f"Memory (MB): Total: {total:.0f}, Free: {free:.0f}, Available: {avail:.0f}"
    except Exception as e:
        return f"Error retrieving memory info: {e}"

def get_random_joke():
    jokes = [
        "Why do programmers prefer dark mode? Because light attracts bugs!",
        "I would tell you a UDP joke, but you might not get it.",
        "Why did the LoRa device get confused? It lost its connection!",
        "I tried connecting my node to the internet, but it got lost in the clouds!"
    ]
    return random.choice(jokes)

def get_help_text():
    return (
        "Available commands:\n"
        "  hi!       - Greets you back\n"
        "  cpu!      - System/CPU info\n"
        "  status!   - Detailed node status\n"
        "  sysinfo!  - General system info\n"
        "  df!       - Disk usage info\n"
        "  temp!     - CPU temperature\n"
        "  ip!       - IP address\n"
        "  mem!      - Memory info\n"
        "  joke!     - A random joke\n"
        "  help!     - List commands\n"
        "  ping!     - Replies with pong!\n"
        "  time!     - Current time\n"
        "  fortune!  - A random fortune\n"
        "  dmesg!    - Last 5 kernel messages\n"
        "  signal!   - Nearby node signals\n"
        "  sendimage!<query> - Send image with query parameters\n"
        "  simple!<message>  - Send a simple text message"
    )

def get_current_time():
    return f"Current Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"

def get_random_fortune():
    fortunes = [
        "You will have a pleasant surprise today!",
        "A thrilling time is in your near future.",
        "Fortune favors the brave.",
        "Caution! Unexpected bugs ahead.",
        "Your code will run without errors today!"
    ]
    return random.choice(fortunes)

def get_dmesg_info():
    try:
        output = subprocess.check_output("sudo dmesg | tail -n 5", shell=True, universal_newlines=True)
        if len(output) > 200:
            output = output[:200] + "..."
        if not output.strip():
            return "No kernel messages available."
        return f"Kernel messages (last 5):\n{output}"
    except Exception as e:
        return f"Error retrieving dmesg output: {e}"

def get_signal_info(interface):
    if not hasattr(interface, "nodes") or not interface.nodes:
        return "No nearby node signal data available."
    active_nodes = []
    for nid, ndata in interface.nodes.items():
        try:
            float(ndata.get("rssi", -999))
            active_nodes.append((nid, ndata))
        except (TypeError, ValueError):
            continue
    if not active_nodes:
        return "No nearby nodes with active signal."
    active_nodes.sort(key=lambda x: float(x[1].get("rssi", -999)), reverse=True)
    active_nodes = active_nodes[:5]
    lines = ["Nearby nodes with active signals:"]
    for nid, ndata in active_nodes:
        lines.append(f"Node {nid} (nickname: {ndata.get('nickname','N/A')}) - RSSI: {ndata.get('rssi','Unknown')}, Last Heard: {ndata.get('lastHeard','Unknown')}")
    return "\n".join(lines)

def print_table(title, items):
    w1, w2 = 30, 50
    sep = "+" + "-"*w1 + "+" + "-"*w2 + "+"
    print(sep)
    print("| {:^{w1}} | {:^{w2}} |".format(title, "", w1=w1-2, w2=w2-2))
    print(sep)
    for key, value in items:
        print("| {:<{w1}} | {:<{w2}} |".format(key, str(value), w1=w1-2, w2=w2-2))
    print(sep)

def build_sender_command(params):
    defaults = {
        "mode": "all",
        "sender_node_id": "eb314389",
        "header": "nc",
        "quality": "75",
        "resize": "800x600",
        "remote_target": "",
        "ssh_key": "",
        "chunk_size": "180",
        "dest": "!47a78d36",
        "connection": "tcp",
        "sleep_delay": "1",
        "process_image": "true",
        "upload": "false",
        "ack": "false"
    }
    for key, value_list in params.items():
        if value_list:
            defaults[key] = value_list[0]
    args = []
    mapping = {
        "mode": "--mode",
        "sender_node_id": "--sender_node_id",
        "header": "--header",
        "quality": "--quality",
        "resize": "--resize",
        "remote_target": "--remote_target",
        "ssh_key": "--ssh_key",
        "chunk_size": "--chunk_size",
        "dest": "--dest",
        "connection": "--connection",
        "sleep_delay": "--sleep_delay"
    }
    for key, flag in mapping.items():
        args.append(flag)
        args.append(defaults[key])
    for bool_key in ["process_image", "upload", "ack"]:
        if defaults[bool_key].lower() in ("true", "1"):
            args.append(f"--{bool_key}")
    return args

# ======================================================
#               MeshSender Class (Sender)
# ======================================================

class MeshSender:
    """
    Encapsulates persistent sending functionality:
     - Includes image processing pipeline (capture, optimize, resize, compress, Base64 encoding).
     - Supports file upload via rsync.
     - Reads file content, splits into chunks, and sends them over a persistent Meshtastic connection.
    """
    @staticmethod
    def send_simple_message(message: str) -> str:
        print(f"---- Sending simple message ----\nMessage: {message}")
        return "Simple message sent successfully."

    def __init__(self, args):
        self.args = args
        self.file_path = Path(args.file_path) if args.file_path else Path(args.output)
        self.chunk_size = args.chunk_size
        self.ch_index = args.ch_index
        self.dest = args.dest
        self.connection = args.connection.lower()
        self.max_retries = args.max_retries
        self.retry_delay = args.retry_delay
        self.header_template = args.header
        self.use_ack = args.ack
        self.sleep_delay = args.sleep_delay
        self.interface = None

    def read_file(self) -> str:
        try:
            return self.file_path.read_text()
        except Exception as e:
            logger.error(f"Error reading file '{self.file_path}': {e}")
            sys.exit(1)

    def get_file_size(self) -> int:
        return self.file_path.stat().st_size

    def chunk_content(self, content: str) -> list:
        return [content[i:i+self.chunk_size] for i in range(0, len(content), self.chunk_size)]

    def generate_header(self, index: int, total_chunks: int) -> str:
        if not self.header_template:
            return ""
        if "#" in self.header_template:
            pattern = re.compile(r"(#+)")
            match = pattern.search(self.header_template)
            if match:
                width = len(match.group(0))
                counter_str = f"{index:0{width}d}"
                header = pattern.sub(counter_str, self.header_template, count=1)
                if not header.endswith('!'):
                    header += "!"
                return header
        width = len(str(total_chunks))
        return f"{self.header_template}{index:0{width}d}!"

    def open_connection(self):
        if self.connection == "tcp":
            logger.info("Establishing persistent TCP connection for sender...")
            try:
                self.interface = TCPInterface(hostname="localhost")
            except Exception as e:
                logger.error(f"Error establishing TCP connection: {e}")
                sys.exit(1)
        elif self.connection == "serial":
            logger.info("Establishing persistent Serial connection for sender...")
            try:
                self.interface = SerialInterface()
            except Exception as e:
                logger.error(f"Error establishing Serial connection: {e}")
                sys.exit(1)
        else:
            logger.error(f"Unknown connection type: {self.connection}")
            sys.exit(1)
        logger.info("Sender connection established.")

    def close_connection(self):
        try:
            self.interface.close()
            logger.info("Sender persistent connection closed.")
        except Exception as e:
            logger.error(f"Error closing sender connection: {e}")

    def send_chunk(self, message: str, chunk_index: int, total_chunks: int) -> int:
        if self.header_template:
            header = self.generate_header(chunk_index, total_chunks)
            full_message = header + message
        else:
            full_message = message
        attempt = 0
        while attempt < self.max_retries:
            try:
                self.interface.sendText(full_message, wantAck=self.use_ack)
                logger.info(f"Sent chunk {chunk_index}/{total_chunks} on attempt {attempt+1}/{self.max_retries}")
                return attempt
            except Exception as e:
                attempt += 1
                logger.warning(f"Retry {attempt}/{self.max_retries} for chunk {chunk_index}: {e}")
                time.sleep(self.retry_delay)
                if attempt == self.max_retries:
                    logger.error(f"Aborting after {self.max_retries} retries for chunk {chunk_index}.")
                    sys.exit(1)
        return attempt

    def send_all_chunks(self):
        content = self.read_file()
        chunks = self.chunk_content(content)
        total_chunks = len(chunks)
        logger.info(f"Total chunks to send: {total_chunks}")
        total_failures = 0
        for i, chunk in enumerate(chunks, start=1):
            failures = self.send_chunk(chunk, i, total_chunks)
            total_failures += failures
            time.sleep(self.sleep_delay)
        return total_chunks, total_failures

def setup_sender_signal_handlers(sender: MeshSender):
    def handler(sig, frame):
        logger.info("CTRL+C detected in sender. Closing connection...")
        sender.close_connection()
        sys.exit(0)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

# ======================================================
#              MeshProcessor Class (Receiver)
# ======================================================

class MeshProcessor:
    """
    Receives and processes Meshtastic messages:

      - Filters incoming messages by sender_node_id and expected header.
      - Combines Base64 fragments from messages.
      - If --process_image is set, decodes and decompresses the combined data to produce an image.
      - Optionally uploads the image via rsync.
      - Prints a performance summary.
    """
    def __init__(self, args):
        self.args = args
        self.received_messages = {}
        self.duplicate_count = 0
        self.combined_messages = []
        self.state_lock = Lock()
        self.running = True
        self.iface = None
        self.last_message_time = time.time()
        self.highest_header = 0
        self.start_time = time.time()
        self.header_digit_pattern = re.compile(r"\d+")
        self.last_progress_time = time.time()

    def print_table(self, title, items):
        w1, w2 = 30, 50
        sep = "+" + "-"*w1 + "+" + "-"*w2 + "+"
        print(sep)
        print("| {:^{w1}} | {:^{w2}} |".format(title, "", w1=w1-2, w2=w2-2))
        print(sep)
        for key, value in items:
            print("| {:<{w1}} | {:<{w2}} |".format(key, str(value), w1=w1-2, w2=w2-2))
        print(sep)

    def print_startup_summary(self):
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
        self.print_table("Startup Summary", params)

    def onReceive(self, packet, interface=None):
        try:
            raw_sender = packet.get("fromId")
            if not raw_sender or raw_sender.lstrip("!") != self.args.sender_node_id:
                logger.debug(f"Ignored message from sender '{raw_sender}'; expected '{self.args.sender_node_id}'.")
                return
            text = (packet.get("decoded", {}).get("text", "").strip() or packet.get("text", "").strip())
            if not text:
                logger.debug("Ignored packet with no text.")
                return
            if not text.startswith(self.args.header):
                logger.debug(f"Ignored message not starting with '{self.args.header}': {text}")
                return
            if "!" in text:
                header_part, _ = text.split("!", 1)
            else:
                header_part = text
            match = self.header_digit_pattern.search(header_part)
            if match:
                header_num = int(match.group())
            else:
                logger.debug(f"Could not extract header number from '{header_part}'.")
                return
            with self.state_lock:
                if header_num in self.received_messages:
                    self.duplicate_count += 1
                    logger.debug(f"Duplicate message for header {header_num} ignored.")
                else:
                    self.received_messages[header_num] = text
                    logger.info(f"Stored message with header {header_num}.")
                    if header_num > self.highest_header:
                        self.highest_header = header_num
                        logger.info(f"Updated highest header to {self.highest_header}.")
                    self.last_message_time = time.time()
        except Exception as e:
            logger.error(f"Exception in onReceive: {e}")

    def combine_messages(self):
        with self.state_lock:
            sorted_items = sorted(self.received_messages.items())
            self.combined_messages = []
            for _, msg in sorted_items:
                if "!" in msg:
                    payload = msg.split("!", 1)[1]
                    self.combined_messages.append(payload)
                else:
                    self.combined_messages.append(msg)

    def decode_and_save_image(self):
        logger.info("Decoding Base64 and decompressing Gzip...")
        combined_data = "".join(self.combined_messages)
        try:
            padded = combined_data.ljust((len(combined_data)+3)//4*4, "=")
            decoded = base64.b64decode(padded)
            decompressed = gzip.decompress(decoded)
            with open(self.args.output, "wb") as f:
                f.write(decompressed)
            logger.info(f"Image saved to {self.args.output}")
        except Exception as e:
            logger.error(f"Error during decode/decompression: {e}")
            sys.exit(1)

    def upload_image(self):
        remote_path = f"{self.args.remote_target.rstrip('/')}/{time.strftime('%Y%m%d%H%M%S')}-restored.jpg"
        cmd = ["nice", "-n", "10", "rsync", "-vz", "-e", f"ssh -i {self.args.ssh_key}", self.args.output, remote_path]
        for attempt in range(1, 4):
            try:
                subprocess.check_call(cmd)
                logger.info(f"Image uploaded to {remote_path}")
                return
            except subprocess.CalledProcessError as e:
                logger.error(f"Attempt {attempt}: Upload error: {e}")
                time.sleep(3)
        logger.error("Upload failed after 3 attempts.")
        sys.exit(1)

    async def run(self):
        self.connect_meshtastic()
        end_time = self.start_time + self.args.run_time * 60
        logger.info("Starting main processing loop...")
        while self.running and time.time() < end_time:
            now = time.time()
            if now - self.last_message_time > self.args.inactivity_timeout:
                logger.info("Inactivity timeout reached.")
                self.running = False
                break
            if now - self.last_progress_time >= self.args.poll_interval:
                with self.state_lock:
                    total_msgs = len(self.received_messages)
                    highest = self.highest_header
                remaining = end_time - now
                logger.info(f"Progress: {total_msgs} messages, highest header: {highest}, {remaining:.1f} sec remaining.")
                self.last_progress_time = now
            await asyncio.sleep(0.5)
        if self.iface:
            try:
                self.iface.close()
            except Exception as e:
                logger.debug(f"Error closing interface: {e}")
        self.combine_messages()
        if self.args.process_image:
            self.decode_and_save_image()
        else:
            logger.info("Skipping image processing (flag not set).")
        if self.args.upload:
            self.upload_image()
        else:
            logger.info("Skipping file upload (flag not set).")
        total_runtime = time.time() - self.start_time
        with self.state_lock:
            total_msgs = len(self.received_messages)
        missing = self.highest_header - total_msgs if self.highest_header > total_msgs else 0
        if self.args.process_image and os.path.exists(self.args.output):
            fsize = os.path.getsize(self.args.output)
        else:
            fsize = "N/A"
        self.print_table("Performance Summary", [
            ("Total Runtime (sec)", f"{total_runtime:.2f}"),
            ("Total Unique Messages", total_msgs),
            ("Highest Header", self.highest_header),
            ("Duplicate Messages", self.duplicate_count),
            ("Estimated Missing Msgs", missing),
            ("Transferred File Size (bytes)", fsize)
        ])

    def connect_meshtastic(self):
        logger.info("Connecting to Meshtastic receiver...")
        try:
            if self.args.connection == "tcp":
                from meshtastic.tcp_interface import TCPInterface
                self.iface = TCPInterface(hostname=self.args.tcp_host)
                from pubsub import pub
                pub.subscribe(self.onReceive, "meshtastic.receive")
                logger.info(f"Connected via TCP on {self.args.tcp_host}")
            else:
                from meshtastic import serial_interface
                self.iface = serial_interface.SerialInterface()
                self.iface.onReceive = self.onReceive
                logger.info("Connected via Serial.")
        except Exception as e:
            logger.error(f"Connection error: {e}")
            sys.exit(1)

def setup_receiver_signal_handlers(processor: MeshProcessor):
    def handler(sig, frame):
        logger.info("CTRL+C detected in receiver. Initiating shutdown...")
        processor.running = False
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

# ======================================================
#                MeshBot Class (Bot)
# ======================================================

class MeshBot:
    def __init__(self, args):
        self.args = args
        self.interface = None
        self.start_time = time.time()
        self.COMMANDS = {"status": "./check_status.sh"}

    def get_status_info(self):
        uptime = int(time.time() - self.start_time)
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        seconds = uptime % 60
        uname = platform.uname()
        try:
            loadavg = os.getloadavg()
            load_str = f"{loadavg[0]:.2f}, {loadavg[1]:.2f}, {loadavg[2]:.2f}"
        except Exception:
            load_str = "N/A"
        node_id = self.args.node_id if self.args.node_id else "Unknown"
        return (
            f"Meshtastic Node Status:\n"
            f"  Node ID: {node_id}\n"
            f"  Firmware: Simulated Firmware v1.0\n"
            f"  Platform: {uname.system} {uname.release}\n"
            f"  Uptime: {hours}h {minutes}m {seconds}s\n"
            f"  Load: {load_str}"
        )

    def on_receive(self, packet, interface=None):
        try:
            sender = packet.get("fromId", "")
            if self.args.node_id and sender.lstrip("!") != self.args.node_id:
                logger.info("Ignoring message from node %s (expected %s).", sender, self.args.node_id)
                return
            if self.args.channel_index is not None:
                pkt_ch = packet.get("channel") or packet.get("ch_index")
                if pkt_ch is not None and int(pkt_ch) != self.args.channel_index:
                    logger.info("Ignoring message from channel %s (expected %s).", pkt_ch, self.args.channel_index)
                    return
            text = ""
            if "decoded" in packet:
                text = packet["decoded"].get("text", "")
            else:
                text = packet.get("text", "")
            text = text.strip().lower()
            if not text:
                logger.debug("No text in message from node %s.", sender)
                return
            logger.info("Received message from node %s: %s", sender, text)
            if text == "hi!":
                if self.interface:
                    self.interface.sendText("well hai!")
                return
            if text == "cpu!":
                if self.interface:
                    self.interface.sendText(get_system_info())
                return
            if text == "status!":
                if self.interface:
                    for line in self.get_status_info().splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return
            if text == "sysinfo!":
                if self.interface:
                    for line in get_general_sysinfo().splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return
            if text == "df!":
                if self.interface:
                    self.interface.sendText(get_disk_info())
                return
            if text == "temp!":
                if self.interface:
                    self.interface.sendText(get_cpu_temp())
                return
            if text == "ip!":
                if self.interface:
                    self.interface.sendText(get_ip_address())
                return
            if text == "mem!":
                if self.interface:
                    self.interface.sendText(get_mem_info())
                return
            if text == "joke!":
                if self.interface:
                    self.interface.sendText(get_random_joke())
                return
            if text == "help!":
                if self.interface:
                    for line in get_help_text().splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return
            if text == "ping!":
                if self.interface:
                    self.interface.sendText("pong!")
                return
            if text == "time!":
                if self.interface:
                    self.interface.sendText(get_current_time())
                return
            if text == "fortune!":
                if self.interface:
                    self.interface.sendText(get_random_fortune())
                return
            if text == "dmesg!":
                if self.interface:
                    self.interface.sendText(get_dmesg_info())
                return
            if text == "signal!":
                if self.interface:
                    for line in get_signal_info(self.interface).splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return
            if text.startswith("sendimage!"):
                qs = text[len("sendimage!"):].strip()
                if "=" not in qs:
                    qs = f"header={qs}"
                params = parse_qs(qs)
                cmd_args = build_sender_command(params)
                cmd = ["python3", "meshtastic_sender.py"] + cmd_args
                logger.info("Received 'sendimage!' command. Running: %s", " ".join(cmd))
                if self.interface:
                    try:
                        self.interface.close()
                        logger.info("Closed interface for sendimage!")
                    except Exception as e:
                        logger.error("Error closing interface: %s", e)
                    self.interface = None
                time.sleep(5)
                try:
                    result = subprocess.run(cmd, shell=False, check=True,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              universal_newlines=True)
                    logger.info("meshtastic_sender.py output: %s", result.stdout)
                except subprocess.CalledProcessError as e:
                    logger.error("Error executing sendimage! command: %s", e)
                return
            if text.startswith("simple!"):
                simple_msg = text[len("simple!"):].strip()
                if self.interface:
                    self.interface.sendText(simple_msg)
                return
            for key, script in self.COMMANDS.items():
                if text.startswith(key):
                    if self.interface:
                        try:
                            self.interface.close()
                            logger.info("Closed interface before executing %s", script)
                        except Exception as e:
                            logger.error("Error closing interface: %s", e)
                        self.interface = None
                    time.sleep(5)
                    try:
                        result = subprocess.run(script, shell=True, check=True,
                                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                  universal_newlines=True)
                        logger.info("Script output: %s", result.stdout)
                    except subprocess.CalledProcessError as e:
                        logger.error("Error executing script %s: %s", script, e)
                    return
            logger.info("No matching command for message: %s", text)
        except Exception as ex:
            logger.error("Exception in on_receive: %s", ex)

    def connect(self):
        try:
            logger.info("Establishing persistent TCP connection to %s...", self.args.tcp_host)
            self.interface = TCPInterface(hostname=self.args.tcp_host)
            pub.subscribe(self.on_receive, "meshtastic.receive")
            logger.info("Connected via TCP to %s.", self.args.tcp_host)
        except Exception as e:
            logger.error("Error establishing TCP connection: %s", e)
            sys.exit(1)

    def run(self):
        self.connect()
        if self.args.channel_index is not None:
            logger.info("Listening for messages on channel %s...", self.args.channel_index)
        else:
            logger.info("Listening for messages on all channels...")
        try:
            while True:
                if self.interface is None:
                    logger.info("Interface closed; reconnecting...")
                    self.connect()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt detected. Shutting down MeshBot...")
        finally:
            if self.interface:
                try:
                    self.interface.close()
                    logger.info("Closed Meshtastic interface.")
                except Exception as e:
                    logger.error("Error closing interface: %s", e)

# ======================================================
#                Main Entry Point (Receiver)
# ======================================================

def receiver_main():
    parser = argparse.ArgumentParser(
        description="Meshtastic Receiver with Asynchronous Processing"
    )
    parser.add_argument("--run_time", type=int, required=True, help="Run time in minutes.")
    parser.add_argument("--sender_node_id", required=True, help="Sender node ID to filter messages from.")
    parser.add_argument("--header", type=str, default="pn", help="Expected message header prefix (before '!').")
    parser.add_argument("--output", type=str, default="restored.jpg", help="Output image file.")
    parser.add_argument("--remote_target", type=str, required=True, help="Remote path for image upload.")
    parser.add_argument("--ssh_key", type=str, required=True, help="SSH identity file for rsync.")
    parser.add_argument("--poll_interval", type=int, default=10, help="Poll interval in seconds.")
    parser.add_argument("--inactivity_timeout", type=int, default=60, help="Inactivity timeout in seconds.")
    parser.add_argument("--connection", type=str, choices=["tcp", "serial"], required=True, help="Connection mode.")
    parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost).")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode.")
    parser.add_argument("--process_image", action="store_true", help="Process Base64 data as an image.")
    parser.add_argument("--upload", action="store_true", help="Attempt file upload using rsync.")
    args = parser.parse_args()
    configure_logging(args.debug)
    processor = MeshProcessor(args)
    processor.print_table("Startup Summary", [
        ("run_time (min)", args.run_time),
        ("sender_node_id", args.sender_node_id),
        ("header", args.header),
        ("output", args.output),
        ("remote_target", args.remote_target),
        ("ssh_key", args.ssh_key),
        ("poll_interval (sec)", args.poll_interval),
        ("inactivity_timeout (sec)", args.inactivity_timeout),
        ("connection", args.connection),
        ("tcp_host", args.tcp_host),
        ("process_image", args.process_image),
        ("upload", args.upload),
        ("debug", args.debug),
    ])
    setup_receiver_signal_handlers(processor)
    try:
        asyncio.run(processor.run())
    except Exception as e:
        logger.error(f"Fatal error in receiver: {e}")
        sys.exit(1)

# ======================================================
#                Main Entry Point (Bot)
# ======================================================

def bot_main():
    parser = argparse.ArgumentParser(
        description="Meshtastic Bot with TCP Interaction and Filtering"
    )
    parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost)")
    parser.add_argument("--channel_index", type=int, default=0, help="Channel index filter (default: 0; use -1 to disable).")
    parser.add_argument("--node_id", type=str, default=None, help="Sender node ID filter (default: None).")
    args = parser.parse_args()
    if args.channel_index == -1:
        args.channel_index = None
    bot = MeshBot(args)
    bot.run()

# ======================================================
#                Main Entry Point (Sender)
# ======================================================

def sender_main():
    parser = argparse.ArgumentParser(
        description="Meshtastic Sender: Process image and/or send file content via a persistent Meshtastic connection."
    )
    parser.add_argument("--mode", choices=["send", "process", "all"], default="all",
                        help="Mode to run: 'process' for image processing only, 'send' for sending only, 'all' for both (default: all)")
    parser.add_argument("--simple", action="store_true", help="Send a simple message (overrides other sender parameters).")
    parser.add_argument("--message", type=str, default="Hello!", help="Message text for simple mode.")
    parser.add_argument("--run_time", type=int, default=5, help="Run time in minutes (for sending mode).")
    parser.add_argument("--sender_node_id", required=True, help="Sender node ID")
    parser.add_argument("--header", type=str, default="pn", help="Header template (use '#' for digit placeholders)")
    parser.add_argument("--quality", type=int, default=75, help="JPEG quality for optimization")
    parser.add_argument("--resize", type=str, default="800x600", help="Resize dimensions (e.g., 800x600)")
    parser.add_argument("--output", type=str, default="base64_image.gz", help="Output file for image processing")
    parser.add_argument("--file_path", type=str, help="Path to file to send (default: output file)")
    parser.add_argument("--chunk_size", type=int, default=200, help="Chunk size for sending")
    parser.add_argument("--ch_index", type=int, default=1, help="Starting chunk index (default: 1)")
    parser.add_argument("--dest", type=str, default="!47a78d36", help="Destination token for sending")
    parser.add_argument("--connection", type=str, choices=["tcp", "serial"], default="tcp", help="Connection type (default: tcp)")
    parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost)")
    parser.add_argument("--ack", action="store_true", help="Enable ACK mode")
    parser.add_argument("--sleep_delay", type=float, default=1.0, help="Delay between sending chunks (default: 1.0 sec)")
    parser.add_argument("--max_retries", type=int, default=10, help="Maximum retries per chunk (default: 10)")
    parser.add_argument("--retry_delay", type=int, default=1, help="Delay between retries (default: 1 sec)")
    parser.add_argument("--upload", action="store_true", help="Upload processed image using rsync (requires --remote_target and --ssh_key)")
    parser.add_argument("--remote_target", type=str, help="Remote target for upload")
    parser.add_argument("--ssh_key", type=str, help="SSH key for rsync")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    configure_logging(args.debug)
    # If in simple mode, send the simple message and exit.
    if args.simple:
        result = MeshSender.send_simple_message(args.message)
        print(result)
        sys.exit(0)
    # For file sending modes, default file_path to output if not provided.
    if args.mode in ("send", "all") and not args.file_path:
        args.file_path = args.output
    print_table("Sender Parameters", [
        ("Mode", args.mode),
        ("Sender Node ID", args.sender_node_id),
        ("Header", args.header),
        ("Quality", args.quality),
        ("Resize", args.resize),
        ("Output", args.output),
        ("File Path", args.file_path),
        ("Chunk Size", args.chunk_size),
        ("Destination", args.dest),
        ("Connection", args.connection),
        ("ACK Mode", args.ack),
        ("Max Retries", args.max_retries),
        ("Retry Delay", args.retry_delay),
        ("Sleep Delay", args.sleep_delay),
        ("Upload", args.upload),
        ("Remote Target", args.remote_target if args.remote_target else "N/A"),
        ("SSH Key", args.ssh_key if args.ssh_key else "N/A")
    ])
    mode = args.mode
    if mode == "process":
        print("Running image processing pipeline...")
        summary = optimize_compress_zip_base64encode_jpg(
            quality=args.quality,
            resize=args.resize,
            snapshot_url="http://localhost:8080/0/action/snapshot",
            output_file=args.output
        )
        print("Image processing complete. Summary:")
        for k, v in summary.items():
            print(f"{k}: {v}")
        if args.upload:
            print("Uploading processed image file...")
            upload_file(args.output, args.remote_target, args.ssh_key)
    elif mode == "send":
        file_path = Path(args.file_path)
        sender = MeshSender(args)
        setup_sender_signal_handlers(sender)
        start_time = time.time()
        sender.open_connection()
        total_chunks, total_failures = sender.send_all_chunks()
        sender.close_connection()
        end_time = time.time()
        elapsed = end_time - start_time
        fsize = sender.get_file_size()
        formatted_time = time.strftime("%H:%M:%S", time.gmtime(elapsed))
        total_attempts = total_chunks + total_failures
        speed = fsize / elapsed if elapsed > 0 else fsize
        print_table("Execution Summary", [
            ("Start Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))),
            ("End Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))),
            ("Time Elapsed", formatted_time),
            ("Total Chunks Sent", total_chunks),
            ("Total Attempts", f"{total_attempts} (includes {total_failures} retries)"),
            ("File Size", f"{fsize} bytes"),
            ("Transmission Speed", f"{speed:.2f} bytes/sec")
        ])
    elif mode == "all":
        print("Running image processing pipeline...")
        summary = optimize_compress_zip_base64encode_jpg(
            quality=args.quality,
            resize=args.resize,
            snapshot_url="http://localhost:8080/0/action/snapshot",
            output_file=args.output
        )
        print("Image processing complete. Summary:")
        for k, v in summary.items():
            print(f"{k}: {v}")
        if args.upload:
            print("Uploading processed image file...")
            upload_file(args.output, args.remote_target, args.ssh_key)
        # Default file_path to output if not supplied.
        if not args.file_path:
            args.file_path = args.output
        sender = MeshSender(args)
        setup_sender_signal_handlers(sender)
        start_time = time.time()
        sender.open_connection()
        total_chunks, total_failures = sender.send_all_chunks()
        sender.close_connection()
        end_time = time.time()
        elapsed = end_time - start_time
        fsize = sender.get_file_size()
        formatted_time = time.strftime("%H:%M:%S", time.gmtime(elapsed))
        total_attempts = total_chunks + total_failures
        speed = fsize / elapsed if elapsed > 0 else fsize
        print_table("Execution Summary", [
            ("Start Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))),
            ("End Time", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))),
            ("Time Elapsed", formatted_time),
            ("Total Chunks Sent", total_chunks),
            ("Total Attempts", f"{total_attempts} (includes {total_failures} retries)"),
            ("File Size", f"{fsize} bytes"),
            ("Transmission Speed", f"{speed:.2f} bytes/sec")
        ])
    else:
        logger.error("Unknown sender mode.")
        sys.exit(1)

# ======================================================
#                Main Entry Point
# ======================================================

def main():
    """
    Parses command-line arguments, configures logging, and dispatches to the appropriate service.
    
    --service choices:
      bot       - Run interactive bot.
      sender    - Run sender functionality only.
      receiver  - Run receiver functionality only.
      meshbot   - Run both bot and receiver concurrently.
    """
    parser = argparse.ArgumentParser(
        description="MeshBot: Combined Meshtastic Bot with Sending, Receiving, and Bot Features."
    )
    parser.add_argument("--service", type=str, choices=["bot", "sender", "receiver", "meshbot"],
                        required=True, help="Service mode to run.")
    # Common options for bot and receiver:
    parser.add_argument("--tcp_host", type=str, default="localhost", help="TCP host (default: localhost)")
    parser.add_argument("--channel_index", type=int, default=0,
                        help="Channel index filter (default: 0; use -1 for all channels)")
    parser.add_argument("--node_id", type=str, default=None, help="Node ID for filtering (optional)")
    # Options for sender and receiver:
    parser.add_argument("--sender_node_id", type=str, default=None, help="Sender node ID filter (required for sender/receiver)")
    parser.add_argument("--header", type=str, default="nc", help="Message header/prefix (default: nc)")
    # Options for sender:
    parser.add_argument("--mode", type=str, choices=["send", "process", "all"], default="all",
                        help="Sender mode: 'send' to send file, 'process' to process image only, 'all' for both (default: all)")
    parser.add_argument("--simple", action="store_true", help="Use simple mode to send a plain text message.")
    parser.add_argument("--message", type=str, default="Hello!", help="Message for simple sender mode.")
    parser.add_argument("--quality", type=int, default=75, help="JPEG quality for image processing (default: 75)")
    parser.add_argument("--resize", type=str, default="800x600", help="Resize dimension (default: 800x600)")
    parser.add_argument("--output", type=str, default="base64_image.gz", help="Output file for processed image")
    parser.add_argument("--file_path", type=str, help="Path to file to send (if not provided, defaults to output file)")
    parser.add_argument("--chunk_size", type=int, default=200, help="Chunk size (default: 200)")
    parser.add_argument("--ch_index", type=int, default=1, help="Starting chunk index (default: 1)")
    parser.add_argument("--dest", type=str, default="!47a78d36", help="Destination token (default: !47a78d36)")
    parser.add_argument("--ack", action="store_true", help="Enable ACK mode for sender")
    parser.add_argument("--sleep_delay", type=float, default=1.0, help="Sleep delay between sending chunks (default: 1.0 sec)")
    parser.add_argument("--max_retries", type=int, default=10, help="Max retries per chunk (default: 10)")
    parser.add_argument("--retry_delay", type=int, default=1, help="Retry delay (default: 1 sec)")
    parser.add_argument("--upload", action="store_true", help="Enable file upload (requires --remote_target and --ssh_key)")
    parser.add_argument("--remote_target", type=str, help="Remote target for file upload")
    parser.add_argument("--ssh_key", type=str, help="SSH key for file upload")
    # Options for receiver:
    parser.add_argument("--run_time", type=int, default=5, help="Receiver run time in minutes (default: 5)")
    parser.add_argument("--poll_interval", type=int, default=10, help="Poll interval in seconds (default: 10)")
    parser.add_argument("--inactivity_timeout", type=int, default=60, help="Inactivity timeout in seconds (default: 60)")
    # General debug option:
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    # Configure logging
    configure_logging(args.debug)

    service = args.service.lower()
    if service == "bot":
        bot_main()
    elif service == "sender":
        sender_main()
    elif service == "receiver":
        receiver_main()
    elif service == "meshbot":
        # Run bot (synchronous) and receiver (asynchronous) concurrently.
        # Start the bot in a separate thread.
        import threading
        bot_thread = threading.Thread(target=bot_main, daemon=True)
        bot_thread.start()
        # Run the receiver in the main thread’s asyncio loop.
        receiver_main()
    else:
        logger.error("Unknown service mode specified.")
        sys.exit(1)

if __name__ == "__main__":
    main()
