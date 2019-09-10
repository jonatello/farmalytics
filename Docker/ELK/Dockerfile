FROM sebp/elk

RUN rm /etc/logstash/conf.d/*
ADD farmalytics.conf /etc/logstash/conf.d/farmalytics.conf
ADD elasticsearch.yml /etc/elasticsearch/elasticsearch.yml

#COPY farmalytics.template.json farmalytics.template.json
#RUN curl -XGET http://localhost:5601/api/saved_objects/index-pattern/farmalytics-*
#RUN curl -XPUT http://localhost:9200/_template/filebeat -H 'Content-Type: application/json' -d @farmalytics.template.json
#COPY start_farmalytics.sh start_farmalytics.sh
#RUN chmod +x start_farmalytics.sh
#RUN ./start_farmalytics.sh

ENTRYPOINT /usr/local/bin/start.sh