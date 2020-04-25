FROM arm32v7/python:3

# Run updates
RUN apt-get -y update && apt-get -y upgrade

# Intall the Python modules
RUN pip install --no-cache-dir rpi.gpio Adafruit_DHT requests prometheus_client

# Setup folder structure and volume mounts
RUN mkdir /farmalytics
WORKDIR /farmalytics
ADD start.py start.py

# Launch entrypoint script
ENTRYPOINT python /farmalytics/start.py