#!/bin/bash

elastic_version="7.3.0"

go get -v github.com/elastic/beats
cd ~/go/src/github.com/elastic/beats/filebeat/
git checkout "v${elastic_version}"
GOARCH=arm go build
cp filebeat ~/
cd
rm -rf go