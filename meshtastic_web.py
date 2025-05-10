from flask import Flask, render_template, request, jsonify
import subprocess
import os
import logging
from meshtastic_bot import get_consolidated_sysinfo
import tailer

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MeshtasticWeb")

# ASCII Art Header
art = '''
          .-------------------------------------------------.
          |          Welcome to the FreeBSD Castle          |
          |  Beware the horned daemon roaming these dark halls  |
          '-------------------------------------------------'

                      /\\          /\\         /\\
                     /  \\        /  \\       /  \\
                    /    \\      /    \\     /    \\
                   /  ^   \\    /  ^   \\   /  ^   \\     <-- Horns galore!
                  /  / \\   \\  /  / \\   \\ /  / \\   \\
                 /  /   \\   \\/  /   \\   X  /   \\   \\
                /__/_____\\____/_____\\____/_____\\___\\

                           .-"""-.
                          /       \\
                         |  (o) (o) |
                         |    ^    |
                         |  \\___/  |
                          \\_______/
                 The Horned Beastie at your service!
'''

print(art)

# ---------------------- Routes ----------------------

@app.route("/")
def home():
    """Homepage with ASCII art, status, and links."""
    try:
        sysinfo = get_consolidated_sysinfo()
    except Exception as e:
        logger.error(f"Error fetching status: {e}")
        sysinfo = "Error fetching status."
    return render_template("home.html", art=art, sysinfo=sysinfo)


@app.route("/status")
def status():
    """Status page showing node and network details."""
    try:
        sysinfo = get_consolidated_sysinfo()
        return render_template("status.html", sysinfo=sysinfo)
    except Exception as e:
        logger.error(f"Error fetching status: {e}")
        return render_template("status.html", sysinfo="Error fetching status.")


@app.route("/send", methods=["POST"])
def send_message():
    """Send a custom message to the Meshtastic network."""
    message = request.form.get("message")
    destination = request.form.get("destination", "broadcast")
    try:
        # Example command to send a message using meshtastic_sender.py
        cmd = [
            "python3",
            "meshtastic_sender.py",
            "--mode", "file_transfer",
            "--file_path", message,
            "--dest", destination,
        ]
        subprocess.run(cmd, check=True)
        return jsonify({"status": "success", "message": "Message sent successfully!"})
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({"status": "error", "message": "Failed to send message."})


@app.route("/restart", methods=["POST"])
def restart_service():
    """Restart the Meshtastic bot service."""
    try:
        subprocess.run(["sudo", "systemctl", "restart", "meshtastic_bot.service"], check=True)
        return jsonify({"status": "success", "message": "Service restarted successfully!"})
    except Exception as e:
        logger.error(f"Error restarting service: {e}")
        return jsonify({"status": "error", "message": "Failed to restart service."})


@app.route("/reboot", methods=["POST"])
def reboot_system():
    """Reboot the system."""
    try:
        subprocess.run(["sudo", "reboot"], check=True)
        return jsonify({"status": "success", "message": "System reboot initiated!"})
    except Exception as e:
        logger.error(f"Error rebooting system: {e}")
        return jsonify({"status": "error", "message": "Failed to reboot system."})


@app.route("/logs")
def logs():
    """Serve the last 20 lines of the log file."""
    try:
        log_file_path = "/home/pi/debug_messages.log"  # Update this path if needed
        with open(log_file_path, "r") as log_file:
            log_lines = tailer.tail(log_file, 20)  # Get the last 20 lines
        return "\n".join(log_lines)
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        return "Error reading logs."


# ---------------------- Run the App ----------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
