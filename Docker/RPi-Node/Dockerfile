# BUILD-USING:          docker build -t farmalytics .
# RUN-USING:            docker container run -d --name farmalytics -v /home/pi/farmalytics/logs:/farmalytics/logs --privileged farmalytics

# Python Base Image from https://hub.docker.com/r/arm32v7/python/
FROM arm32v7/python:3

# Run updates
RUN apt-get -y update && apt-get -y upgrade && apt-get install -y cron

# Intall the Python modules
RUN pip install --no-cache-dir rpi.gpio Adafruit_DHT requests

# Setup cron job
COPY crontab /etc/cron.d/cjob
RUN chmod 0644 /etc/cron.d/cjob

# Setup folder structure and volume mounts
RUN mkdir /farmalytics
WORKDIR /farmalytics
RUN mkdir logs
VOLUME logs
ADD scripts scripts
VOLUME scripts/config.py

# Setup filebeat
COPY filebeat filebeat
COPY filebeat.yml filebeat.yml
RUN chmod +x filebeat

# Start filebeat
CMD cron && ./filebeat -e -c filebeat.yml