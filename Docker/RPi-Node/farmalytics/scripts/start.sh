#!/bin/bash

# Start cron
cron

# Create env var loader script to be used with cron jobs
printenv | sed 's/^\(.*\)$/export \1/g' > /farmalytics/scripts/load_env.sh
chmod +x /farmalytics/scripts/load_env.sh

# Update logstash host IP
sed -i 's/<logstash_host_ip>/'"$LOGSTASH_HOST_IP"'/' filebeat.yml

# Start filebeat
/farmalytics/filebeat -e -c filebeat.yml