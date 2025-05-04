#!/usr/bin/env python3
"""
meshtastic_bot.py - Improved Meshtastic Bot

This bot uses a persistent TCP connection (via Meshtastic’s API)
to listen for incoming messages. It applies node and channel filtering.
When a message is received, the bot performs one of these actions:
  - If text is exactly "hi!", it replies with "well hai!".
  - If text is exactly "top!", it replies with basic system info.
  - If text is exactly "status!", it replies with detailed node status info,
    sending each line as a separate message.
  - If text is exactly "sysinfo!", it replies with general system information,
    sending each line separately.
  - If text is exactly "df!", it replies with disk usage info.
  - If text is exactly "temp!", it replies with CPU temperature.
  - If text is exactly "ip!", it replies with the primary IP address.
  - If text is exactly "mem!", it replies with memory info.
  - If text is exactly "joke!", it replies with a random joke.
  - If text is exactly "help!", it replies with a list of commands.
  - If text is exactly "ping!", it replies with "pong!".
  - If text is exactly "time!", it replies with the current local time.
  - If text is exactly "fortune!", it replies with a random fortune message.
  - If text is exactly "dmesg!", it replies with the last 5 kernel log messages (truncated if needed).
  - If text is exactly "signal!", it replies with information about nearby nodes (from the interface’s nodes registry).
  - Otherwise, if the text begins with a key in COMMANDS (e.g., "sendimage!"),
    it will close the connection, wait a few seconds, and execute the associated shell script.
  
After any shell-script command (which closes the connection), the main loop
re‑establishes the connection to continue listening.

Usage Examples:
  python3 meshtastic_bot.py --tcp_host localhost --channel_index 0 --node_id fb123456
  (Use --channel_index -1 to disable channel filtering)

This script uses robust logging (to both console and a rotating file)
and includes handling for connection management and direct message replies.
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
import random

# Import Meshtastic TCP interface and the pubsub mechanism.
from meshtastic.tcp_interface import TCPInterface
from pubsub import pub


# ---------------------- Logging Configuration ----------------------
logger = logging.getLogger("MeshtasticBot")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s"
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.handlers.RotatingFileHandler(
    "meshtastic_bot.log", maxBytes=1024 * 1024, backupCount=3
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


# ---------------------- Utility Functions ----------------------
def get_system_info():
    """
    Gather basic system summary (for the "top!" command).
    """
    uname = platform.uname()
    info = [f"System: {uname.system} {uname.node} {uname.release}"]
    try:
        loadavg = os.getloadavg()
        info.append(f"Load: {loadavg[0]:.2f}, {loadavg[1]:.2f}, {loadavg[2]:.2f}")
    except Exception:
        info.append("Load: N/A")
    return " | ".join(info)

def get_general_sysinfo():
    """
    Gather general system information (for the "sysinfo!" command).
    """
    uname = platform.uname()
    python_version = platform.python_version()
    return (
         f"General System Info:\n"
         f"  System:    {uname.system}\n"
         f"  Node:      {uname.node}\n"
         f"  Release:   {uname.release}\n"
         f"  Version:   {uname.version}\n"
         f"  Machine:   {uname.machine}\n"
         f"  Processor: {uname.processor}\n"
         f"  Python:    {python_version}"
    )

def get_disk_info():
    """
    Gather disk usage information (for the "df!" command).
    """
    try:
        total, used, free = shutil.disk_usage("/")
        total_gb = total / (1024**3)
        used_gb = used / (1024**3)
        free_gb = free / (1024**3)
        return (
            f"Disk Usage (/):\n"
            f"  Total: {total_gb:.2f} GB\n"
            f"  Used:  {used_gb:.2f} GB\n"
            f"  Free:  {free_gb:.2f} GB"
        )
    except Exception as e:
        return f"Error retrieving disk info: {e}"

def get_cpu_temp():
    """
    Retrieve CPU temperature (for the "temp!" command).
    """
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_milli = int(f.read().strip())
            temp_c = temp_milli / 1000.0
            return f"CPU Temperature: {temp_c:.1f}°C"
    except Exception as e:
        return f"Error reading CPU temperature: {e}"

def get_ip_address():
    """
    Retrieve the primary IP address (for the "ip!" command).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"IP Address: {ip}"
    except Exception as e:
        return f"Error determining IP address: {e}"

def get_mem_info():
    """
    Gather memory usage information (for the "mem!" command) by reading /proc/meminfo.
    """
    try:
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
        return f"Memory (MB): Total: {total_mb:.0f}, Free: {free_mb:.0f}, Available: {avail_mb:.0f}"
    except Exception as e:
        return f"Error retrieving memory info: {e}"

def get_random_joke():
    """
    Return a random joke.
    """
    jokes = [
         "Why do programmers prefer dark mode? Because light attracts bugs!",
         "I would tell you a UDP joke, but you might not get it.",
         "Why did the LoRa device get confused? It lost its connection!",
         "I tried connecting my node to the internet, but it got lost in the clouds!"
    ]
    return random.choice(jokes)

def get_help_text():
    """
    Return help text listing all available commands.
    """
    return (
        "Available commands:\n"
        "  hi!      - Greets you back\n"
        "  top!     - Basic system info\n"
        "  status!  - Detailed node status (sent as separate lines)\n"
        "  sysinfo! - General system information (sent as separate lines)\n"
        "  df!      - Disk usage info\n"
        "  temp!    - CPU temperature\n"
        "  ip!      - IP address\n"
        "  mem!     - Memory info\n"
        "  joke!    - Tell a random joke\n"
        "  help!    - List available commands\n"
        "  ping!    - Replies with pong!\n"
        "  time!    - Current local time\n"
        "  fortune! - A random fortune message\n"
        "  dmesg!   - Last 5 kernel log messages (truncated if too long)\n"
        "  signal!  - Lists nearby nodes with direct signal info\n"
        "Shell-script commands (if configured): e.g., sendimage!"
    )

def get_current_time():
    """
    Return the current local date and time (for the "time!" command).
    """
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return f"Current Time: {now}"

def get_random_fortune():
    """
    Return a random fortune.
    """
    fortunes = [
         "You will have a pleasant surprise today!",
         "A thrilling time is in your near future.",
         "Fortune favors the brave.",
         "Caution! Unexpected bugs ahead.",
         "Your code will run without errors today!"
    ]
    return random.choice(fortunes)

def get_dmesg_info():
    """
    Retrieve the last 5 lines of the kernel ring buffer (for the "dmesg!" command).
    If the output is too long, truncate it to 200 characters.
    """
    try:
        output = subprocess.check_output("dmesg | tail -n 5", shell=True, universal_newlines=True)
        max_length = 200
        if len(output) > max_length:
            output = output[:max_length] + "..."
        return f"Kernel messages (last 5):\n{output}"
    except Exception as e:
        return f"Error retrieving dmesg output: {e}"

def get_signal_info(interface):
    """
    Gather information about nearby nodes from the interface's node registry.
    Returns a multi-line string with details about each node (ID, nickname, RSSI, last heard).
    """
    if not hasattr(interface, "nodes") or not interface.nodes:
        return "No nearby node signal data available."
    info_lines = []
    info_lines.append("Nearby nodes:")
    for node_id, node_data in interface.nodes.items():
        nickname = node_data.get("nickname", "N/A")
        rssi = node_data.get("rssi", "Unknown")
        last_heard = node_data.get("lastHeard", "Unknown")
        info_lines.append(f"Node {node_id} (nickname: {nickname}) - RSSI: {rssi}, Last Heard: {last_heard}")
    return "\n".join(info_lines)


# ---------------------- Bot Class ----------------------
class MeshtasticBot:
    def __init__(self, args):
        global logger
        self.args = args
        self.interface = None
        self.start_time = time.time()  # For uptime reporting
        # Map shell-script commands.
        self.COMMANDS = {
            "sendimage!": "./send_image.sh",
            "status": "./check_status.sh",
            # Additional shell-script commands can be added here.
        }

    def get_status_info(self):
        """
        Gather detailed node status: uptime, platform details, and load averages.
        """
        uptime_seconds = time.time() - self.start_time
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        seconds = int(uptime_seconds % 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"
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
            f"  Uptime: {uptime_str}\n"
            f"  Load: {load_str}"
        )

    def on_receive(self, packet, interface=None):
        global logger
        try:
            sender = packet.get("fromId", "")
            # Filter by node_id if configured.
            if self.args.node_id and sender.lstrip("!") != self.args.node_id:
                logger.info("Ignoring message from node %s (expected %s).", sender, self.args.node_id)
                return

            # If channel filtering is enabled, check channel info.
            if self.args.channel_index is not None:
                packet_channel = packet.get("channel") or packet.get("ch_index")
                if packet_channel is not None:
                    try:
                        if int(packet_channel) != self.args.channel_index:
                            logger.info("Ignoring message from channel %s (expected %s).", packet_channel, self.args.channel_index)
                            return
                    except Exception as e:
                        logger.warning("Channel filtering error: %s", e)

            # Extract and normalize the message text.
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

            # Direct reply commands.
            if text == "hi!":
                logger.info("Received 'hi!' command; replying 'well hai!'")
                if self.interface:
                    self.interface.sendText("well hai!")
                return

            if text == "top!":
                logger.info("Received 'top!' command; sending basic system info")
                if self.interface:
                    self.interface.sendText(get_system_info())
                return

            if text == "status!":
                logger.info("Received 'status!' command; sending detailed status info")
                if self.interface:
                    status_output = self.get_status_info()
                    for line in status_output.splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return

            if text == "sysinfo!":
                logger.info("Received 'sysinfo!' command; sending general system info")
                if self.interface:
                    sysinfo_output = get_general_sysinfo()
                    for line in sysinfo_output.splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return

            if text == "df!":
                logger.info("Received 'df!' command; sending disk usage info")
                if self.interface:
                    self.interface.sendText(get_disk_info())
                return

            if text == "temp!":
                logger.info("Received 'temp!' command; sending CPU temperature")
                if self.interface:
                    self.interface.sendText(get_cpu_temp())
                return

            if text == "ip!":
                logger.info("Received 'ip!' command; sending IP address")
                if self.interface:
                    self.interface.sendText(get_ip_address())
                return

            if text == "mem!":
                logger.info("Received 'mem!' command; sending memory info")
                if self.interface:
                    self.interface.sendText(get_mem_info())
                return

            if text == "joke!":
                logger.info("Received 'joke!' command; sending a joke")
                if self.interface:
                    self.interface.sendText(get_random_joke())
                return

            if text == "help!":
                logger.info("Received 'help!' command; sending help text")
                if self.interface:
                    self.interface.sendText(get_help_text())
                return

            if text == "ping!":
                logger.info("Received 'ping!' command; replying with pong!")
                if self.interface:
                    self.interface.sendText("pong!")
                return

            if text == "time!":
                logger.info("Received 'time!' command; sending current time")
                if self.interface:
                    self.interface.sendText(get_current_time())
                return

            if text == "fortune!":
                logger.info("Received 'fortune!' command; sending a fortune")
                if self.interface:
                    self.interface.sendText(get_random_fortune())
                return

            if text == "dmesg!":
                logger.info("Received 'dmesg!' command; sending last 5 kernel messages")
                if self.interface:
                    self.interface.sendText(get_dmesg_info())
                return

            if text == "signal!":
                logger.info("Received 'signal!' command; sending nearby node signal information")
                if self.interface:
                    signal_response = get_signal_info(self.interface)
                    for line in signal_response.splitlines():
                        self.interface.sendText(line)
                        time.sleep(0.5)
                return

            # For shell-script driven commands.
            for cmd, script in self.COMMANDS.items():
                if text.startswith(cmd):
                    logger.info("Command '%s' recognized from node %s; executing script: %s", cmd, sender, script)
                    if self.interface:
                        try:
                            self.interface.close()
                            logger.info("Closed Meshtastic interface before executing: %s", script)
                        except Exception as e:
                            logger.error("Error closing interface: %s", e)
                        self.interface = None
                    time.sleep(2)
                    try:
                        subprocess.run(script, shell=True, check=True)
                    except subprocess.CalledProcessError as e:
                        logger.error("Error executing script '%s': %s", script, e)
                    return

            logger.info("No matching command for message: %s", text)
        except Exception as ex:
            logger.error("Exception in on_receive: %s", ex)

    def connect(self):
        global logger
        try:
            logger.info("Establishing persistent TCP connection to %s...", self.args.tcp_host)
            self.interface = TCPInterface(hostname=self.args.tcp_host)
            pub.subscribe(self.on_receive, "meshtastic.receive")
            logger.info("Connected via TCP to %s.", self.args.tcp_host)
        except Exception as e:
            logger.error("Error establishing TCP connection: %s", e)
            sys.exit(1)

    def run(self):
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
        description="Improved Meshtastic Bot with TCP Interaction, Robust Logging, and Filtering"
    )
    parser.add_argument("--tcp_host", type=str, default="localhost",
                        help="TCP host for Meshtastic connection (default: localhost)")
    parser.add_argument("--channel_index", type=int, default=0,
                        help="Filter messages by channel index (default: 0). Use -1 to disable filtering.")
    parser.add_argument("--node_id", type=str, default=None,
                        help="Filter messages by sender node ID (default: None).")
    args = parser.parse_args()

    if args.channel_index == -1:
        args.channel_index = None

    bot = MeshtasticBot(args)
    bot.run()


if __name__ == "__main__":
    main()
