#!/usr/bin/env python3
"""
Meshtastic Bot

This script provides a robust pipeline for interacting with a Meshtastic mesh network. 
It listens for incoming messages and performs actions based on specific commands.

### Purpose:
1. **Command Handling**:
   - Listens for incoming messages over the Meshtastic network.
   - Responds to specific commands such as "hi!", "sysinfo!", "help!", and "ping!".
   - Supports sending images using query-string parameters.

2. **Persistent Connection**:
   - Maintains a persistent TCP or Serial connection to the Meshtastic device.

3. **Robust Logging**:
   - Logs all activity to both the console and a rotating log file (`debug_messages.log`).

### Parameters:
  - `--connection`: Connection mode (`tcp` or `serial`, default: `tcp`).
  - `--tcp_host`: TCP host for Meshtastic connection (default: `localhost`, used only in `tcp` mode).
  - `--channel_index`: Filter messages by channel index (default: `0`). Use `-1` to disable filtering.
  - `--node_id`: Filter messages by sender node ID (default: `None`).
  - `--debug`: Enables debug mode for detailed logging.

### Commands:
  - `hi!`: Replies with "well hai!".
  - `sysinfo!`: Sends consolidated system info (CPU, memory, disk, IP, and time).
  - `help!`: Shows available commands (line-by-line).
  - `ping!`: Replies with "pong!".
  - `sendimage!<query>`: Sends an image using query-string parameters.

### Usage Examples:
  --- Start the bot and listen for messages ---
  python3 meshtastic_bot.py --connection tcp --tcp_host localhost --channel_index 0 --node_id eb314389

  --- Enable debug mode ---
  python3 meshtastic_bot.py --debug

Use `--help` for full details on all parameters.
"""

import time
import argparse
import logging
import logging.handlers
import subprocess
import sys
import platform
import os
import shutil
import socket
from urllib.parse import parse_qs

from meshtastic.tcp_interface import TCPInterface
from meshtastic.serial_interface import SerialInterface
from pubsub import pub

# The sender logic remains in meshtastic_sender.py.
SENDER_SCRIPT = "meshtastic_sender.py"

# ---------------------- Logging Configuration ----------------------
def configure_logging(debug_mode):
    """
    Configures logging to stream to stdout and write to a rotating log file.

    Args:
      debug_mode (bool): If True, set log level to DEBUG; otherwise, INFO.
    """
    log_level = logging.DEBUG if debug_mode else logging.INFO
    logger = logging.getLogger("MeshtasticBot")
    logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if not debug_mode else logging.DEBUG)
    console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.handlers.RotatingFileHandler("debug_messages.log", maxBytes=1024 * 1024, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    return logger


logger = None  # Will be initialized in the main function

# ---------------------- Utility Functions ----------------------
def get_consolidated_sysinfo():
    """Return consolidated system info for the 'sysinfo!' command."""
    try:
        # CPU and system info
        uname = platform.uname()
        loadavg = os.getloadavg()
        cpu_info = f"System: {uname.system} {uname.node} {uname.release} | Load: {loadavg[0]:.2f}, {loadavg[1]:.2f}, {loadavg[2]:.2f}"

        # Memory info
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) > 1:
                    key = parts[0].strip()
                    value = parts[1].strip().split()[0]
                    meminfo[key] = int(value)
        total_mb = meminfo.get("MemTotal", 0) / 1024
        free_mb = meminfo.get("MemFree", 0) / 1024
        avail_mb = meminfo.get("MemAvailable", free_mb) / 1024
        mem_info = f"Memory (MB): Total: {total_mb:.0f}, Free: {free_mb:.0f}, Available: {avail_mb:.0f}"

        # Disk usage info
        total, used, free = shutil.disk_usage("/")
        total_gb = total / (1024 ** 3)
        used_gb = used / (1024 ** 3)
        free_gb = free / (1024 ** 3)
        disk_info = f"Disk Usage (/): Total: {total_gb:.2f} GB, Used: {used_gb:.2f} GB, Free: {free_gb:.2f} GB"

        # IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        ip_info = f"IP Address: {ip}"

        # Current time
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        time_info = f"Current Time: {now}"

        # Consolidated info
        return f"{cpu_info}\n{mem_info}\n{disk_info}\n{ip_info}\n{time_info}"
    except Exception as e:
        return f"Error retrieving system info: {e}"

def get_help_text():
    """Return help text listing all available commands."""
    return (
        "Available commands:\n"
        "  hi!               - Greets you back\n"
        "  sysinfo!          - Consolidated system info (CPU, memory, disk, IP, and time)\n"
        "  help!             - Show this help message (line-by-line)\n"
        "  ping!             - Replies with pong!\n"
        "  sendimage!<query> - Sends an image using query-string parameters\n"
        "                      For example:\n"
        "                      sendimage!header=myHeader&chunk_size=180&resize=800x600&quality=75\n"
    )

# ---------------------- Bot Class ----------------------
class MeshtasticBot:
    def __init__(self, args):
        global logger
        self.args = args
        self.interface = None

    def connect(self):
        """
        Establishes a connection to the Meshtastic device using either TCP or Serial.
        """
        global logger
        try:
            if self.args.connection == "tcp":
                logger.info("Establishing persistent TCP connection to %s...", self.args.tcp_host)
                self.interface = TCPInterface(hostname=self.args.tcp_host)
                pub.subscribe(self.on_receive, "meshtastic.receive")
                logger.info("Connected via TCP to %s.", self.args.tcp_host)
            elif self.args.connection == "serial":
                logger.info("Establishing persistent Serial connection...")
                self.interface = SerialInterface()
                pub.subscribe(self.on_receive, "meshtastic.receive")
                logger.info("Connected via Serial.")
            else:
                logger.error("Invalid connection mode: %s. Use 'tcp' or 'serial'.", self.args.connection)
                sys.exit(1)
        except Exception as e:
            logger.error("Error establishing connection: %s", e)
            sys.exit(1)

    def on_receive(self, packet, interface=None):
        """
        Handles incoming messages and executes commands based on the message content.
        """
        global logger
        try:
            sender = packet.get("fromId", "")
            if self.args.node_id and sender.lstrip("!") != self.args.node_id:
                logger.info("Ignoring message from node %s (expected %s).", sender, self.args.node_id)
                return

            if self.args.channel_index is not None:
                packet_channel = packet.get("channel") or packet.get("ch_index")
                if packet_channel is not None:
                    try:
                        if int(packet_channel) != self.args.channel_index:
                            logger.info("Ignoring message from channel %s (expected %s).", packet_channel, self.args.channel_index)
                            return
                    except Exception as e:
                        logger.warning("Channel filtering error: %s", e)

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
                logger.info("Received 'hi!' command; replying 'well hai!'")
                if self.interface:
                    self.interface.sendText("well hai!")
                return

            if text == "sysinfo!":
                logger.info("Received 'sysinfo!' command; sending consolidated system info")
                if self.interface:
                    for line in get_consolidated_sysinfo().splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return

            if text == "help!":
                logger.info("Received 'help!' command; sending help text")
                if self.interface:
                    for line in get_help_text().splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return

            if text == "ping!":
                logger.info("Received 'ping!' command; replying with pong!")
                if self.interface:
                    self.interface.sendText("pong!")
                return

            # Handle the sendimage! command using query-string style.
            if text.startswith("sendimage!"):
                qs_string = text[len("sendimage!"):].strip()
                # If no "=" is present, assume the entire string is the header.
                if "=" not in qs_string:
                    qs_string = f"header={qs_string}"
                params = parse_qs(qs_string)
                cmd_args = build_sender_command(params)
                cmd = ["python3", SENDER_SCRIPT] + cmd_args
                logger.info("Received 'sendimage!' command. Running: %s", " ".join(cmd))
                if self.interface:
                    try:
                        self.interface.close()
                        logger.info("Closed Meshtastic interface for sendimage!")
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

            logger.info("No matching command for message: %s", text)
        except Exception as ex:
            logger.error("Exception in on_receive: %s", ex)

    def run(self):
        """
        Runs the bot, maintaining a persistent connection and listening for messages.
        """
        global logger
        self.connect()
        if self.args.channel_index is not None:
            logger.info("Listening for messages on channel %s...", self.args.channel_index)
        else:
            logger.info("Listening for messages on all channels...")
        try:
            while True:
                if self.interface is None:
                    logger.info("Interface closed. Re-establishing connection...")
                    self.connect()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Shutting down MeshtasticBot...")
        finally:
            if self.interface:
                try:
                    self.interface.close()
                    logger.info("Closed Meshtastic interface.")
                except Exception as e:
                    logger.error("Error closing Meshtastic interface: %s", e)

# ---------------------- Main Entry Point ----------------------
def main():
    parser = argparse.ArgumentParser(
        description="Meshtastic Bot with TCP/Serial Interaction, Robust Logging, and Filtering"
    )
    parser.add_argument("--connection", type=str, choices=["tcp", "serial"], default="tcp",
                        help="Connection mode: 'tcp' or 'serial' (default: tcp)")
    parser.add_argument("--tcp_host", type=str, default="localhost",
                        help="TCP host for Meshtastic connection (default: localhost, used only in TCP mode)")
    parser.add_argument("--channel_index", type=int, default=0,
                        help="Filter messages by channel index (default: 0). Use -1 to disable filtering.")
    parser.add_argument("--node_id", type=str, default=None,
                        help="Filter messages by sender node ID (default: None).")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode for detailed logging.")
    args = parser.parse_args()

    if args.connection == "tcp" and not args.tcp_host:
        parser.error("--tcp_host is required when connection mode is 'tcp'.")

    if args.channel_index == -1:
        args.channel_index = None

    global logger
    logger = configure_logging(args.debug)

    bot = MeshtasticBot(args)
    bot.run()

if __name__ == "__main__":
    main()
