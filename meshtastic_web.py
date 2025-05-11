from flask import Flask, render_template, request, jsonify, send_file
import subprocess
import os
import logging
from meshtastic_bot import get_consolidated_sysinfo
import tailer

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MeshtasticWeb")

# ---------------------- Routes ----------------------

@app.route("/")
def home():
    """Homepage with status and controls."""
    try:
        sysinfo = get_consolidated_sysinfo()
    except Exception as e:
        logger.error(f"Error fetching status: {e}")
        sysinfo = "Error fetching status."
    return render_template("home.html", sysinfo=sysinfo)


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
        cmd = [
            "python3",
            "meshtastic_sender.py",
            "--mode", "message",
            "--message", message,
            "--dest", destination,
        ]
        subprocess.run(cmd, check=True)
        return jsonify({"status": "success", "message": "Message sent successfully!"})
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({"status": "error", "message": "Failed to send message."})


@app.route("/restartbot", methods=["POST"])
def restart_bot_service():
    """Restart the Meshtastic bot service."""
    try:
        subprocess.run(["sudo", "systemctl", "restart", "meshtastic_bot.service"], check=True)
        return jsonify({"status": "success", "message": "Bot Service restarted successfully!"})
    except Exception as e:
        logger.error(f"Error restarting bot service: {e}")
        return jsonify({"status": "error", "message": "Failed to restart bot service."})


@app.route("/restartweb", methods=["POST"])
def restart_web_service():
    """Restart the Meshtastic web service."""
    try:
        subprocess.run(["sudo", "systemctl", "restart", "meshtastic_web.service"], check=True)
        return jsonify({"status": "success", "message": "Web Service restarted successfully!"})
    except Exception as e:
        logger.error(f"Error restarting web service: {e}")
        return jsonify({"status": "error", "message": "Failed to restart web service."})


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
        log_file_path = "/home/pi/debug_messages.log"
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as log_file:
            log_lines = tailer.tail(log_file, 20)
        return "<br>".join(log_lines)
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        return jsonify({"status": "error", "message": "Error reading logs."})


@app.route("/download_logs")
def download_logs():
    """Serve the entire debug_messages.log file as a downloadable attachment."""
    try:
        log_file_path = "/home/pi/debug_messages.log"
        return send_file(
            log_file_path,
            as_attachment=True,
            download_name="debug_messages.log",
            mimetype="text/plain"
        )
    except Exception as e:
        logger.error(f"Error serving log file for download: {e}")
        return jsonify({"status": "error", "message": "Error downloading log file."})


# ---------------------- Run the App ----------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
