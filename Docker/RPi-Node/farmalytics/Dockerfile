FROM arm32v7/python:3

# Run updates
RUN apt-get -y update && apt-get -y upgrade && apt-get install -y cron logrotate git golang

# Intall the Python modules
RUN pip install --no-cache-dir rpi.gpio Adafruit_DHT requests

# Setup folder structure and volume mounts
RUN mkdir /farmalytics
WORKDIR /farmalytics
RUN mkdir /var/log/farmalytics
VOLUME /var/log/farmalytics
ADD scripts scripts
RUN chmod -R +x scripts
VOLUME /farmalytics/scripts

# Setup cron job
COPY crontab /etc/cron.d/farmalytics
RUN chmod 0644 /etc/cron.d/farmalytics

# Build filebeat and copy over config
RUN scripts/build_filebeat.sh
COPY filebeat.yml .

# Setup logrotate
COPY logrotate /etc/logrotate.d/farmalytics

# Launch entrypoint script
ENTRYPOINT /farmalytics/scripts/start.sh