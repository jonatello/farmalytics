FROM balenalib/raspberrypi3

RUN apt-get update && apt-get -y upgrade && apt-get -y install motion

# Copy config file and make it mountable
COPY motion.conf /etc/motion/
VOLUME /etc/motion

# Make video target dir mountable
VOLUME /var/lib/motion

EXPOSE 8080 8081

ENTRYPOINT ["motion"]