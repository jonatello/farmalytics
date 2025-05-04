#!/usr/bin/env python3
"""
meshtastic_bot.py - Improved Meshtastic Bot

This bot uses a persistent TCP connection (via Meshtastic’s API)
to listen for incoming messages. It applies node and channel filtering.
When a message beginning with a recognized header (e.g., "sendimage!" or "status")
is detected, the bot executes the corresponding shell script.

Usage Examples:
  python3 meshtastic_bot.py --tcp_host localhost --channel_index 0 --node_id fb123456
  (Pass --channel_index -1 to disable channel filtering)

This script uses robust logging (both to console and to a rotating file)
and follows common patterns for error handling and message filtering.
"""

import time
import argparse
import logging
import logging.handlers
import subprocess
import sys

# Import Meshtastic TCP interface and the pubsub mechanism.
from meshtastic.tcp_interface import TCPInterface
from pubsub import pub

# ---------------------- Logging Configuration ----------------------
logger = logging.getLogger("MeshtasticBot")
logger.setLevel(logging.DEBUG)  # Capture all logs

formatter = logging.Formatter(
    "%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s"
)

# Console handler at INFO level
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Rotating file handler at DEBUG level (rotates at 1 MB, keeps 3 backups)
file_handler = logging.handlers.RotatingFileHandler(
    "meshtastic_bot.log", maxBytes=1024 * 1024, backupCount=3
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


# ---------------------- Bot Class ----------------------
class MeshtasticBot:
    def __init__(self, args):
        """
        Initializes the bot with command-line parameters.
        
        Args:
          args: Parsed command-line arguments.
        """
        self.args = args
        self.interface = None
        # Map commands to their respective shell scripts.
        self.COMMANDS = {
            "sendimage!": "./send_image.sh",  # trigger image sending via the sender script
            "status": "./check_status.sh",     # trigger status check
            # Add additional commands as needed.
        }

    def on_receive(self, packet, interface=None):
        """
        Callback triggered upon receiving a Meshtastic message.

        The packet is expected to be a dictionary that contains:
          - "fromId": The sending node (may be prefixed with "!" that we strip).
          - "decoded": A dictionary containing a "text" field with the message content.
        
        Filtering:
          - If --node_id is specified, only messages from that node are processed.
          - If --channel_index is set (other than -1), the message channel is checked.
        
        On matching a known command, the corresponding shell script is executed.
        Before any command is run, the current Meshtastic connection is closed,
        and the bot pauses for 2 seconds to allow the device to reset.
        """
        try:
            sender = packet.get("fromId", "")
            # Filter by node_id (if provided)
            if self.args.node_id and sender.lstrip("!") != self.args.node_id:
                logger.info("Ignoring message from node %s (expected %s).",
                            sender, self.args.node_id)
                return

            # If channel filtering is enabled, check for channel information.
            if self.args.channel_index is not None:
                # Some packets include channel info under "channel" or "ch_index".
                packet_channel = packet.get("channel") or packet.get("ch_index")
                if packet_channel is not None:
                    try:
                        if int(packet_channel) != self.args.channel_index:
                            logger.info("Ignoring message from channel %s (expected %s).",
                                        packet_channel, self.args.channel_index)
                            return
                    except Exception as e:
                        logger.warning("Channel filtering error: %s", e)

            # Extract the message text. Prefer the "decoded" field if present.
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

            # Check for known commands and execute the corresponding shell script.
            for cmd, script in self.COMMANDS.items():
                if text.startswith(cmd):
                    logger.info("Command '%s' recognized from node %s; executing script: %s",
                                cmd, sender, script)
                    
                    # Close connection and pause for all commands.
                    if self.interface:
                        try:
                            self.interface.close()
                            logger.info("Closed Meshtastic interface before launching script: %s", script)
                        except Exception as e:
                            logger.error("Error closing Meshtastic interface: %s", e)
                    time.sleep(2)

                    try:
                        subprocess.run(script, shell=True, check=True)
                    except subprocess.CalledProcessError as e:
                        logger.error("Error executing script %s: %s", script, e)
                    return

            logger.info("No matching command for message: %s", text)
        except Exception as ex:
            logger.error("Exception in on_receive: %s", ex)

    def connect(self):
        """
        Establishes a persistent TCP connection using Meshtastic’s TCPInterface.
        Subscribes the on_receive callback to incoming messages.
        """
        try:
            logger.info("Establishing persistent TCP connection to %s...", self.args.tcp_host)
            self.interface = TCPInterface(hostname=self.args.tcp_host)
            pub.subscribe(self.on_receive, "meshtastic.receive")
            logger.info("Connected via TCP to %s.", self.args.tcp_host)
        except Exception as e:
            logger.error("Error establishing TCP connection: %s", e)
            sys.exit(1)

    def run(self):
        """
        Connects to the Meshtastic device and enters an infinite loop listening for messages.
        Shuts down cleanly upon KeyboardInterrupt.
        """
        self.connect()
        if self.args.channel_index is not None:
            logger.info("Listening for messages on channel %s...", self.args.channel_index)
        else:
            logger.info("Listening for messages on all channels...")
        try:
            while True:
                # Sleep briefly to reduce CPU usage.
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
                        help="Filter messages by channel index (default: 0). Use -1 to disable channel filtering.")
    parser.add_argument("--node_id", type=str, default=None,
                        help="Filter messages by sender node ID (default: None).")
    args = parser.parse_args()

    # If channel_index is passed as -1, disable filtering by channel.
    if args.channel_index == -1:
        args.channel_index = None

    bot = MeshtasticBot(args)
    bot.run()


if __name__ == "__main__":
    main()
