#!/bin/bash

# Create default farmalytics-* index pattern
curl -POST http://localhost:5601/api/saved_objects/index-pattern/farmalytics -d '{"attributes":{"title" : "farmalytics-*",  "timeFieldName": "@timestamp"}}' -H 'Content-Type: application/json' -H 'kbn-xsrf: true'
# Upload index template
curl -XPUT 'http://localhost:9200/_template/filebeat' -H 'Content-Type: application/json' -d @'../../farmalytics.template.json'