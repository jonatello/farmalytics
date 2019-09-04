# farmalytics Docker

Most of the information will be within the wiki - https://github.com/jonatello/farmalytics/wiki

The goal of this Docker folder is to make the setup and configuration of the pi nodes and the ELK stack as simple as possible. For a new Raspberry Pi node first you must build the filebeat binary (a script has been provided - "build_filebeat.sh"). Edit the config.py as necessary to match your hardware. Edit the filebeat.yml to point to your logstash host. Then simply install Docker, build, and run.

For a new ELK host, simply install Docker on any machine and run docker-compose up -d from within the ELK directory.
