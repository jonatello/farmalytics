#! /bin/bash

# Step 1) Build
# NOTE: the git checkout version needs to match the elastic search API version
#elastic_version="6.1.1"
elastic_version="7.2"

go get -v github.com/elastic/beats
cd /go/src/github.com/elastic/beats/filebeat/
git checkout "v${elastic_version}"
GOARCH=arm go build
cp filebeat /build
cd /build

# Step 2) Download the tar
download_url="https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-${elastic_version}-linux-x86.tar.gz"
curl $download_url -o download.tar

# Step 3) Untar, add filebeat binary, tar
echo "  Adding the filebeat binary to the tar..."
mkdir workdir
tar -xf download.tar -C workdir --strip-components=1
cp filebeat workdir/filebeat
cd workdir
#tar -zcf ../pibeats-${elastic_version}.tar.gz .
cd ..
#echo "  Cleaning up..."
#rm -rf filebeat
#rm -rf workdir
#rm -rf download.tar

echo "  COMPLETE!"