#! /bin/bash

source meshtastic/bin/activate

./optimize_compress_zip_base64encode_jpg.sh

python3 meshtastic_send.py base64_image.gz --dest '!6209a0bd' --chunk_size 63

deactivate
