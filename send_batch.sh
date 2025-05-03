#! /bin/bash

source meshtastic/bin/activate

./optimize_compress_zip_base64encode_jpg.sh 80 400x300

python3 meshtastic_send.py base64_image.gz --connection tcp --dest '!47a78d36' --chunk_size 180

deactivate
