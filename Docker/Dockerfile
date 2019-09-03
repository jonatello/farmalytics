# BUILD-USING:          docker build -t farmalytics .
# RUN-USING:            docker container run -d -v logs:/farmalytics/logs --privileged farmalytics

# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:3

# Run updates
RUN apt-get -y update && apt-get -y upgrade
RUN apt-get install -y cron

# Setup folder structure and volume mount
RUN mkdir /farmalytics
WORKDIR /farmalytics
RUN mkdir logs
VOLUME logs
ADD scripts scripts

# Copy the Python scripts
COPY config.py ./
VOLUME config.py

# Add farmalytics dir to Python PATH
ENV PYTHONPATH "${PYTHONPATH}:/farmalytics"

# Intall the Python modules
RUN pip install --no-cache-dir rpi.gpio
RUN pip install --no-cache-dir Adafruit_DHT
RUN pip install --no-cache-dir requests

# Setup cron job
COPY crontab /etc/cron.d/cjob
RUN chmod 0644 /etc/cron.d/cjob

# Trigger Python script
CMD cron -f