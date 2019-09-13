#!/bin/bash

# Temporarily set GO path
export GOPATH=/farmalytics/go

elastic_version="7.3.0"

go get -v github.com/elastic/beats
cd /farmalytics/go/src/github.com/elastic/beats/filebeat/
git checkout "v${elastic_version}"
GOARCH=arm go build

# Copy filebeat binary to farmalytics dir
cp filebeat /farmalytics

# Clean up
rm -rf $GOPATH