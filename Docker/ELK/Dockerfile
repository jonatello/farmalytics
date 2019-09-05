# BUILD-USING:          docker build -t farmalytics-elk .
# RUN-USING:            docker container run -d --name farmalytics-elk -v $(pwd)/data:/etc/lib/elasticsearch farmalytics-elk
# TEST-USING:           docker container run -it --rm --name farmalytics-elk -v $(pwd)/data:/etc/lib/elasticsearch farmalytics-elk

FROM sebp/elk

ADD 30-output.conf /etc/logstash/conf.d/30-output.conf
ADD 02-beats-input.conf /etc/logstash/conf.d/02-beats-input.conf
ADD 12-farmalytics-filter.conf /etc/logstash/conf.d/12-farmalytics-filter.conf
ADD elasticsearch.yml /etc/elasticsearch/elasticsearch.yml

#COPY farmalytics.template.json farmalytics.template.json
#RUN curl -XGET http://localhost:5601/api/saved_objects/index-pattern/farmalytics-*
#RUN curl -XPUT http://localhost:9200/_template/filebeat -H 'Content-Type: application/json' -d @farmalytics.template.json
#COPY start_farmalytics.sh start_farmalytics.sh
#RUN chmod +x start_farmalytics.sh
#RUN ./start_farmalytics.sh

ENTRYPOINT /usr/local/bin/start.sh