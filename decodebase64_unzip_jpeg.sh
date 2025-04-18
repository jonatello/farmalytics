#!/bin/bash

# Set variables
base64_image_path="base64_image.gz"
zipped_image_path="compressed_image.gz"
restored_image_path="restored.jpg"

# Function to check command success
check_success() {
    if [ $? -ne 0 ]; then
        echo "Error: $1 failed."
        exit 1
    fi
}

# Function to decode the Base64 file
base64 -d $base64_image_path > $zipped_image_path
check_success "Base64 decoding"

# Function to unzip the file using Python
python3 -c "
import gzip
with open('$zipped_image_path', 'rb') as f_in:
    compressed_data = f_in.read()
data = gzip.decompress(compressed_data)
with open('$restored_image_path', 'wb') as f_out:
    f_out.write(data)
"
check_success "Python unzipping"

rm $base64_image_path
rm $zipped_image_path

# Display the size of the restored image
restored_size=$(stat -c %s $restored_image_path)
echo "Restored image size: $restored_size bytes"

echo "Base64 decoding, unzipping, and restoration complete."
echo "Restored image saved to $restored_image_path"
