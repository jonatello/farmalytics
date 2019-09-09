FROM arm32v7/python:3

# Run updates
RUN apt-get -y update && apt-get -y upgrade && apt-get install -y cron logrotate

# Intall the Python modules
RUN pip install --no-cache-dir rpi.gpio Adafruit_DHT requests

# Setup cron job
COPY crontab /etc/cron.d/farmalytics
RUN chmod 0644 /etc/cron.d/farmalytics

# Setup folder structure and volume mounts
RUN mkdir /farmalytics
WORKDIR /farmalytics
RUN mkdir /var/log/farmalytics
VOLUME /var/log/farmalytics
ADD scripts scripts
COPY config.py scripts/config.py
VOLUME /farmalytics/scripts

# Setup filebeat
COPY filebeat .
COPY filebeat.yml .
RUN chmod +x filebeat

# Setup logrotate
COPY logrotate /etc/logrotate.d/farmalytics

# Start cron and filebeat
ENTRYPOINT cron && ./filebeat -e -c filebeat.yml