# farmalytics Docker

Most of the information will be within the wiki - https://github.com/jonatello/farmalytics/wiki

The goal of this Docker folder is to make the setup and configuration of the pi nodes and the ELK stack as simple as possible. For a new Raspberry Pi node first you must build the filebeat binary (a script has been provided - "build_filebeat.sh"). Update the scripts/config.py as necessary to match your hardware. Update the filebeat.yml to point to your logstash host. Then simply install Docker, build, and run:
```
sudo apt-get update && sudo apt-get -y upgrade
curl -sSL https://get.docker.com | sh
sudo usermod -aG docker pi
docker build -t farmalytics .
docker container run -d --name farmalytics -v /home/pi/farmalytics/logs:/farmalytics/logs --privileged farmalytics
```

For a new ELK host, simply install Docker on any machine and run the following from within the ELK directory:
```
docker-compose up -d
```
