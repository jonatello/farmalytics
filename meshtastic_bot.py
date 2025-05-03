import subprocess  # To execute local scripts and Meshtastic commands
import time        # To manage delays
import logging     # For logging messages
import argparse    # To handle command-line arguments

# ---------------------- Command-Line Argument Parsing ----------------------
parser = argparse.ArgumentParser(description="Meshtastic Bot with Command Execution & Filtering")
parser.add_argument("--channel_index", type=int, default=None, help="Filter messages by channel index (default: all channels)")
parser.add_argument("--node_id", type=str, default=None, help="Filter messages by sender node ID (default: all nodes)")
args = parser.parse_args()

# ---------------------- Configuration ----------------------
# Define commands and their respective actions.
COMMANDS = {
    "sendimage!": "./send_image.sh",  # Runs send_image.sh when "sendimage!" is received
    "status": "./check_status.sh",  # Runs check_status.sh when "status" is received
    # Uncomment and add new commands below:
    # "restart!": "./restart_device.sh",
    # "logs": "./get_logs.sh"
}

# Enable logging for debugging and tracking execution
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# ---------------------- Message Handling ----------------------
def receive_message():
    """
    Continuously listens for new messages from the Meshtastic network.
    - Uses subprocess to call the Meshtastic CLI.
    - Parses incoming messages to trigger corresponding actions.

    Returns:
        dict: A dictionary containing message text, sender node, and channel index.
    """
    try:
        result = subprocess.run("meshtastic --host --receive", shell=True, capture_output=True, text=True)
        message_data = result.stdout.strip().split("\n")  # Process output lines
        
        message_info = {}
        for line in message_data:
            if "text=" in line:
                message_info["text"] = line.split("text=")[-1].strip().lower()  # Extract message content
            if "from=" in line:
                message_info["node_id"] = line.split("from=")[-1].strip()  # Extract sender node ID
            if "ch_index=" in line:
                message_info["channel_index"] = int(line.split("ch_index=")[-1].strip())  # Extract channel index
        
        return message_info if message_info else None
    except subprocess.CalledProcessError as e:
        logger.error(f"Error retrieving messages: {e}")
        return None

def process_message(message_info):
    """
    Checks if the received message matches a predefined command.
    If a match is found, it executes the corresponding script.
    Also applies filtering based on channel and node ID parameters.

    Parameters:
        message_info (dict): Dictionary containing message data.
    """
    if not message_info:
        return
    
    text = message_info.get("text", "")
    sender_node = message_info.get("node_id", "")
    channel_index = message_info.get("channel_index", None)

    # Apply channel filtering based on command-line argument
    if args.channel_index is not None and channel_index != args.channel_index:
        logger.info(f"Ignoring message from channel {channel_index}, only accepting from {args.channel_index}")
        return

    # Apply node filtering based on command-line argument
    if args.node_id is not None and sender_node != args.node_id:
        logger.info(f"Ignoring message from node {sender_node}, only accepting from {args.node_id}")
        return

    # Execute the command if it matches a predefined action
    if text in COMMANDS:
        logger.info(f"Executing: {COMMANDS[text]}")
        subprocess.run(COMMANDS[text], shell=True)  # Run the associated shell script
    else:
        logger.info("No matching command found.")

# ---------------------- Main Execution ----------------------
print("Listening for messages...")

while True:
    received_message_info = receive_message()
    if received_message_info:
        process_message(received_message_info)
    
    time.sleep(1)  # Prevent high CPU usage
