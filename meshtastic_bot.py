#!/usr/bin/env python3
"""
Meshtastic Bot

This script provides a robust pipeline for interacting with a Meshtastic mesh network. 
It listens for incoming messages and performs actions based on specific commands.

### Purpose:
1. **Command Handling**:
   - Listens for incoming messages over the Meshtastic network.
   - Responds to specific commands such as "hi!", "sysinfo!", "help!", "ping!", "restartbot!", "restartweb!" and "reboot!".
   - Supports sending and receiving using query-string parameters.

2. **Persistent Connection**:
   - Maintains a persistent TCP or Serial connection to the Meshtastic device.

3. **Robust Logging**:
   - Logs all activity to both the console and a rotating log file (`debug_messages.log`).

### Parameters:
  - `--connection`: Connection mode (`tcp` or `serial`, default: `tcp`).
  - `--tcp_host`: TCP host for Meshtastic connection (default: `localhost`, used only in `tcp` mode).
  - `--debug`: Enables debug mode for detailed logging.

### Commands:
  - `hi!`: Replies with "well hai!".
  - `sysinfo!`: Sends consolidated system info (CPU, memory, disk, IP, time, and uptime).
  - `help!`: Shows available commands (line-by-line).
  - `ping!`: Replies with "pong!" and includes SNR and RSSI values.
  - `restartbot!`: Restarts the Meshtastic bot service.
  - `restartweb!`: Restarts the Meshtastic web service.
  - `reboot!`: Reboots the operating system.
  - `send!<query>`: Sends messages with meshtastic_sender.py using query-string parameters.
  - `receive!<query>`: Receives messages with meshtastic_receiver.py using query-string parameters.

### Usage Examples:
  --- Start the bot and listen for messages ---
  python3 meshtastic_bot.py --connection tcp --tcp_host localhost

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
import shlex

from meshtastic.tcp_interface import TCPInterface
from meshtastic.serial_interface import SerialInterface
from pubsub import pub

# The sender logic remains in meshtastic_sender.py.
SENDER_SCRIPT = "meshtastic_sender.py"

# The receiver logic remains in meshtastic_receiver.py.
RECEIVER_SCRIPT = "meshtastic_receiver.py"

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
import platform
import os
import time
import socket
import shutil

def get_consolidated_sysinfo():
    """Return consolidated system info for the 'sysinfo!' command."""
    try:
        # CPU and basic system info
        uname = platform.uname()
        loadavg = os.getloadavg()
        cpu_info = (f"System: {uname.system} {uname.node} {uname.release} | "
                    f"Load Avg: {loadavg[0]:.2f}, {loadavg[1]:.2f}, {loadavg[2]:.2f}")

        # Memory info from /proc/meminfo
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) > 1:
                    key = parts[0].strip()
                    # We take only the numeric part (in kB)
                    value = parts[1].strip().split()[0]
                    meminfo[key] = int(value)
        total_mb = meminfo.get("MemTotal", 0) / 1024
        free_mb = meminfo.get("MemFree", 0) / 1024
        avail_mb = meminfo.get("MemAvailable", free_mb) / 1024
        mem_info = f"Memory (MB): Total: {total_mb:.0f}, Free: {free_mb:.0f}, Available: {avail_mb:.0f}"

        # Swap usage info
        swap_total = meminfo.get("SwapTotal", 0) / 1024
        swap_free = meminfo.get("SwapFree", 0) / 1024
        swap_used = swap_total - swap_free
        swap_info = f"Swap (MB): Total: {swap_total:.0f}, Used: {swap_used:.0f}, Free: {swap_free:.0f}"

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

        # Uptime info from /proc/uptime
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
        uptime_days = int(uptime_seconds // (24 * 3600))
        uptime_hours = int((uptime_seconds % (24 * 3600)) // 3600)
        uptime_minutes = int((uptime_seconds % 3600) // 60)
        uptime_info = f"Uptime: {uptime_days}d {uptime_hours}h {uptime_minutes}m"

        # CPU Temperature (usually reported in millidegree Celsius)
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_raw = f.read().strip()
                temperature = int(temp_raw) / 1000.0
            cpu_temp_info = f"CPU Temp: {temperature:.1f}°C"
        except Exception:
            cpu_temp_info = "CPU Temp: N/A"

        # CPU Frequency (scaling_cur_freq is in KHz)
        try:
            with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "r") as f:
                freq_raw = f.read().strip()
                freq_mhz = int(freq_raw) / 1000.0  # Convert to MHz
            cpu_freq_info = f"CPU Frequency: {freq_mhz:.1f} MHz"
        except Exception:
            cpu_freq_info = "CPU Frequency: N/A"

        # Consolidate all info into one multi-line string
        consolidated_info = "\n".join([
            cpu_info,
            mem_info,
            swap_info,
            disk_info,
            ip_info,
            time_info,
            uptime_info,
            cpu_temp_info,
            cpu_freq_info
        ])
        return consolidated_info

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
        "  send!<query>      - Sends messages with meshtastic_sender.py using query-string parameters\n"
        "  receive!<query>   - Receives messages with meshtastic_sender.py using query-string parameters\n"
    )

# ---------------------- Bot Class ----------------------
class MeshtasticBot:
    def __init__(self, args):
        global logger
        self.args = args
        self.connection = args.connection  # Initialize the connection type (tcp or serial)
        self.tcp_host = args.tcp_host  # Initialize the TCP host if needed
        self.interface = None

    def __enter__(self):
        """Context manager entry point: Open the connection."""
        self.open_connection()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Context manager exit point: Close the connection."""
        self.close_connection()

    def open_connection(self):
        """Establishes a persistent Meshtastic connection (TCP or Serial)."""
        retries = 3
        for attempt in range(1, retries + 1):
            try:
                if self.connection == 'tcp':
                    logger.info(f"Attempting to establish TCP connection (Attempt {attempt}/{retries})...")
                    self.interface = TCPInterface(hostname=self.tcp_host)
                elif self.connection == 'serial':
                    logger.info(f"Attempting to establish Serial connection (Attempt {attempt}/{retries})...")
                    self.interface = SerialInterface()
                else:
                    logger.error(f"Unknown connection type: {self.connection}")
                    sys.exit(1)

                # Subscribe to the 'meshtastic.receive' topic
                pub.subscribe(self.on_receive, "meshtastic.receive")
                logger.info("Subscribed to 'meshtastic.receive' topic.")
                logger.info("Persistent connection established.")
                return  # Exit the loop if the connection is successful
            except Exception as e:
                logger.error(f"Error establishing connection (Attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(2)  # Wait before retrying
                else:
                    logger.error("Failed to establish connection after multiple attempts. Exiting.")
                    self.close_connection()
                    sys.exit(1)

    def close_connection(self):
        """Closes the persistent Meshtastic connection."""
        try:
            if self.interface:
                logger.info("Stopping Meshtastic threads...")
                if hasattr(self.interface, "stop"):
                    try:
                        self.interface.stop(timeout=10)  # Gracefully stop threads with a timeout
                        logger.info("Stopped all Meshtastic threads.")
                    except TimeoutError:
                        logger.warning("Timeout while stopping Meshtastic threads. Forcing connection close.")
                    except Exception as e:
                        logger.error(f"Error stopping threads: {e}")
                self.interface.close()
                logger.info("Persistent connection closed.")
        except Exception as e:
            logger.error(f"Error closing connection: {e}")
        finally:
            self.interface = None

    def on_receive(self, packet, interface=None):
        """
        Handles incoming messages and executes commands based on the message content.
        """
        global logger
        try:
            sender = packet.get("fromId", "")
            text = ""
            if "decoded" in packet:
                text = packet["decoded"].get("text", "")
            else:
                text = packet.get("text", "")
            text = text.strip()
            if not text:
                logger.debug("No text in message from node %s.", sender)
                return

            logger.info("Received message from node %s: %s", sender, text)

            if text.startswith("cmd!"):
                command = text[len("cmd!"):].strip()
                logger.info(f"Received 'cmd!' command; executing: {command}")
                try:
                    # Execute the command and capture the output
                    result = subprocess.run(
                        command, shell=True, capture_output=True, text=True
                    )
                    output = result.stdout.strip() or result.stderr.strip() or "Command executed with no output."
                    logger.info(f"Command output: {output}")

                    # Split the output into smaller chunks (160 characters max)
                    def split_message(message, max_length=160):
                        chunks = []
                        current_chunk = ""
                        for line in message.splitlines():
                            if len(current_chunk) + len(line) + 1 > max_length:  # +1 for newline
                                chunks.append(current_chunk)
                                current_chunk = line
                            else:
                                current_chunk += ("\n" if current_chunk else "") + line
                        if current_chunk:
                            chunks.append(current_chunk)
                        return chunks

                    message_chunks = split_message(output)

                    # Send each chunk as a separate message with line numbers
                    if self.interface:
                        try:
                            for i, chunk in enumerate(message_chunks, start=1):
                                numbered_chunk = f"[{i}/{len(message_chunks)}] {chunk}"
                                logger.debug(f"Sending chunk: {numbered_chunk}")
                                self.interface.sendText(numbered_chunk, wantAck=True)
                                time.sleep(1.0)  # Add a short delay between messages
                        except Exception as e:
                            logger.error(f"Error sending chunk {i}/{len(message_chunks)}: {e}")
                            # Continue sending remaining chunks even if one fails
                except Exception as e:
                    logger.error(f"Error executing command: {e}")
                    if self.interface:
                        self.interface.sendText(f"Error executing command: {e}", wantAck=True)
                return

            if text == "hi!":
                logger.info("Received 'hi!' command; replying 'well hai!'")
                if self.interface:
                    try:
                        self.interface.sendText("well hai 😺!", wantAck=True)
                    except Exception as e:
                        logger.error(f"Error sending 'hi!' response: {e}")
                return

            if text == "sysinfo!":
                logger.info("Received 'sysinfo!' command; sending consolidated system info")
                if self.interface:
                    try:
                        sysinfo = get_consolidated_sysinfo()
                        message_chunks = split_message_with_numbers(sysinfo)
                        for i, chunk in enumerate(message_chunks, start=1):
                            numbered_chunk = f"[{i}/{len(message_chunks)}] {chunk}"
                            self.interface.sendText(numbered_chunk, wantAck=True)
                            time.sleep(1.0)
                    except Exception as e:
                        logger.error(f"Error sending system info: {e}")
                return
                
            if text == "meshinfo!":
                logger.info("Received 'meshinfo!' command; sending Meshtastic node details")
                if self.interface:
                    try:
                        for line in self.get_meshtastic_info().splitlines():
                            self.interface.sendText(line, wantAck=True)
                            time.sleep(1.0)  # Add a short delay between messages
                    except Exception as e:
                        logger.error(f"Error sending Meshtastic info: {e}")
                return

            if text == "help!":
                logger.info("Received 'help!' command; sending help text")
                if self.interface:
                    try:
                        help_text = get_help_text()
                        message_chunks = split_message_with_numbers(help_text)
                        for i, chunk in enumerate(message_chunks, start=1):
                            numbered_chunk = f"[{i}/{len(message_chunks)}] {chunk}"
                            self.interface.sendText(numbered_chunk, wantAck=True)
                            time.sleep(1.0)
                    except Exception as e:
                        logger.error(f"Error sending help text: {e}")
                return

            if text == "ping!":
                logger.info("Received 'ping!' command; replying with pong and signal info")
                if self.interface:
                    try:
                        logger.debug(f"Full packet content: {packet}")

                        # Extract SNR and RSSI values from the packet
                        snr = packet.get("rxSnr", "N/A")
                        rssi = packet.get("rxRssi", "N/A")

                        # Prepare the response message
                        response_message = f"pong! SNR: {snr} dB, RSSI: {rssi} dBm"

                        # Send the response
                        self.interface.sendText(response_message, wantAck=True)
                    except Exception as e:
                        logger.error(f"Error sending 'ping!' response: {e}")
                return
            
            if text == "restartbot!":
                logger.info("Received 'restartbot!' command; restarting the bot service")
                try:
                    subprocess.run(["sudo", "systemctl", "restart", "meshtastic_bot.service"], check=True)
                    logger.info("Service restarted successfully.")
                    if self.interface:
                        self.interface.sendText("Bot service restarted successfully.", wantAck=True)
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to restart the bot service: {e}")
                    if self.interface:
                        self.interface.sendText(f"Failed to restart the bot service: {e}", wantAck=True)
                except Exception as e:
                    logger.error(f"Unexpected error during bot restart: {e}")
                    if self.interface:
                        self.interface.sendText(f"Unexpected error during bot restart: {e}", wantAck=True)
                return
            
            if text == "restartweb!":
                logger.info("Received 'restartweb!' command; restarting the web service")
                try:
                    subprocess.run(["sudo", "systemctl", "restart", "meshtastic_web.service"], check=True)
                    logger.info("Web service restarted successfully.")
                    if self.interface:
                        self.interface.sendText("Web service restarted successfully.", wantAck=True)
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to restart the web service: {e}")
                    if self.interface:
                        self.interface.sendText(f"Failed to restart the web service: {e}", wantAck=True)
                except Exception as e:
                    logger.error(f"Unexpected error during web service restart: {e}")
                    if self.interface:
                        self.interface.sendText(f"Unexpected error during web service restart: {e}", wantAck=True)
                return            
            
            if text == "reboot!":
                logger.info("Received 'reboot!' command; rebooting the system")
                try:
                    subprocess.run(["sudo", "reboot"], check=True)
                    logger.info("System reboot initiated successfully.")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to reboot the system: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error during system reboot: {e}")
                return

            if text.startswith("send!"):
                qs_string = text[len("send!"):].strip()
                if "=" not in qs_string:
                    qs_string = f"header={qs_string}"
                params = parse_qs(qs_string)
                cmd = ["python3"] + build_command(params, SENDER_SCRIPT)
                logger.info("Received 'send!' command. Running: %s", " ".join(cmd))

                # Close the Meshtastic connection before running the sender script
                if self.interface:
                    try:
                        self.close_connection()
                        logger.info("Closed Meshtastic interface for send!")
                    except Exception as e:
                        logger.error("Error closing interface: %s", e)

                time.sleep(5)  # Add a short delay to ensure the connection is fully closed

                try:
# Use subprocess.Popen for real-time logging
                    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        # Stream stdout and stderr in real-time
                        for line in process.stdout:
                            logger.info(line.strip())
                        for line in process.stderr:
                            logger.error(line.strip())
                    finally:
                        # Ensure the process streams are closed
                        process.stdout.close()
                        process.stderr.close()

                    # Wait for the process to complete
                    return_code = process.wait()
                    if return_code != 0:
                        logger.error(f"Sender script exited with non-zero status: {return_code}")
                    else:
                        logger.info("Sender script completed successfully.")
                except Exception as e:
                    logger.error(f"Error executing send! command: {e}")
                    if self.interface:
                        self.interface.sendText(f"Error executing send! command: {e}", wantAck=True)
                finally:
                    logger.info("Re-establishing Meshtastic connection after send! command.")
                    self.open_connection()
                    if self.interface:
                        self.interface.sendText("Send command completed successfully.", wantAck=True)
                return

            if text.startswith("receive!"):
                qs_string = text[len("receive!"):].strip()
                if "=" not in qs_string:
                    qs_string = f"output={qs_string}"
                params = parse_qs(qs_string)

                # Handle parameters without values (e.g., "upload")
                for key in list(params.keys()):
                    if not params[key]:
                        params[key] = [""]  # Retain the parameter as an empty string

                # Manually check for standalone flags (e.g., "upload")
                if "upload" in qs_string and "upload" not in params:
                    params["upload"] = [""]

                cmd = ["python3"] + build_command(params, RECEIVER_SCRIPT)
                logger.info("Received 'receive!' command. Running: %s", " ".join(cmd))

                if self.interface:
                    try:
                        self.close_connection()
                        logger.info("Closed Meshtastic interface for receive!")
                    except Exception as e:
                        logger.error("Error closing interface: %s", e)

                time.sleep(5) # Add a short delay to ensure the connection is fully closed

                try:
# Use shlex.split to ensure proper argument handling
                    process = subprocess.Popen(shlex.split(" ".join(cmd)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        # Stream stdout and stderr in real-time
                        for line in process.stdout:
                            logger.info(line.strip())
                        for line in process.stderr:
                            logger.error(line.strip())
                    finally:
                        # Ensure the process streams are closed
                        process.stdout.close()
                        process.stderr.close()

                    # Wait for the process to complete
                    return_code = process.wait()
                    if return_code != 0:
                        logger.error(f"Receiver script exited with non-zero status: {return_code}")
                    else:
                        logger.info("Receiver script completed successfully.")
                    return
                except Exception as e:
                    logger.error(f"Error executing receive! command: {e}")
                    if self.interface:
                        self.interface.sendText(f"Error executing receive! command: {e}", wantAck=True)
                finally:
                    logger.info("Re-establishing Meshtastic connection after receive! command.")
                    self.open_connection()
                    if self.interface:
                        self.interface.sendText("Receive command completed successfully.", wantAck=True)
                return

            logger.info("No matching command for message: %s", text)
        except Exception as ex:
            logger.error("Exception in on_receive: %s", ex)

    def run(self):
        """
        Runs the bot, maintaining a persistent connection and listening for messages.
        """
        global logger
        self.open_connection()
        try:
            while True:
                if self.interface is None:
                    logger.info("Interface closed. Re-establishing connection...")
                    self.open_connection()
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

    def get_meshtastic_info(self):
        """
        Retrieves and formats Meshtastic node details, including firmware version,
        uptime, connected nodes count, battery status, signal strength, and additional metrics.
        """
        try:
            # Retrieve the firmware version.
            node_version = getattr(self.interface, "firmware_version", "Unknown")

            # Retrieve connected nodes count.
            nodes_dict = getattr(self.interface, "nodes", {})
            connected_nodes_count = len(nodes_dict)

            # Retrieve battery status.
            battery_status = getattr(self.interface, "battery_level", "N/A")

            # Retrieve the number of messages sent and received.
            messages_sent = getattr(self.interface, "messages_sent", "N/A")
            messages_received = getattr(self.interface, "messages_received", "N/A")

            # Retrieve hardware model.
            hardware_model = getattr(self.interface, "hardware_model", "Unknown")

            # Build the multi-line response.
            response = (
                f"Version: {node_version}\n"
                f"Hardware Model: {hardware_model}\n"
                f"Connected Nodes: {connected_nodes_count}\n"
                f"Battery: {battery_status}%\n"
                f"Messages Sent: {messages_sent}\n"
                f"Messages Received: {messages_received}\n"
            )
            return response
        except Exception as e:
            logger.error(f"Error retrieving Meshtastic info: {e}")
            return "Error retrieving Meshtastic info."

# ---------------------- Helper Functions ----------------------
def build_command(params, script):
    """
    Builds the command-line arguments for a given script based on query-string parameters.

    Args:
    params (dict): Parsed query-string parameters.
    script (str): The script to execute (e.g., SENDER_SCRIPT or RECEIVER_SCRIPT).

    Returns:
    list: List of command-line arguments including the script name.
    """
    args = [script]
    for key, value in params.items():
        if value:  # If the parameter has a value
            args.append(f"--{key}")
            args.append(value[0])
        else:  # Handle flags like 'upload' that have no value
            args.append(f"--{key}")
    return args

# Split the output into smaller chunks (160 characters max)
def split_message_with_numbers(message, max_length=160):
    chunks = []
    current_chunk = ""
    for line in message.splitlines():
        if len(current_chunk) + len(line) + 1 > max_length:  # +1 for newline
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ("\n" if current_chunk else "") + line
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

# ---------------------- Main Entry Point ----------------------
def main():
    parser = argparse.ArgumentParser(
        description="Meshtastic Bot with TCP/Serial Interaction, Robust Logging, and Filtering"
    )
    parser.add_argument("-c","--connection", type=str, choices=["tcp", "serial"], default="tcp",
                        help="Connection mode: 'tcp' or 'serial' (default: tcp)")
    parser.add_argument("-t","--tcp_host", type=str, default="localhost",
                        help="TCP host for Meshtastic connection (default: localhost, used only in TCP mode)")
    parser.add_argument("-d","--debug", action="store_true",
                        help="Enable debug mode for detailed logging.")
    args = parser.parse_args()

    if args.connection == "tcp" and not args.tcp_host:
        parser.error("--tcp_host is required when connection mode is 'tcp'.")

    global logger
    logger = configure_logging(args.debug)

    bot = MeshtasticBot(args)
    bot.run()

if __name__ == "__main__":
    main()
