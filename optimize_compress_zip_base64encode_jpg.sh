#!/bin/bash

# Set variables
image_path="lastsnap.jpg"
compressed_image_path="compressed.jpg"
zipped_image_path="compressed_image.gz"
base64_image_path="base64_image.gz"

# Function to check command success
check_success() {
    if [ $? -ne 0 ]; then
        echo "Error: $1 failed."
        exit 1
    fi
}

# Capture snapshot with Motion
curl -s http://localhost:8080/0/action/snapshot > /dev/null
check_success "Snapshot capture"
sleep 1
cp /var/lib/motion/lastsnap.jpg ./
check_success "Copy snapshot"
sudo rm /var/lib/motion/*
check_success "Remove old snapshots"

# Get initial file size
initial_size=$(stat -c %s $image_path)
echo "Initial file size: $initial_size bytes"

# Optimize and compress JPEG image using jpegoptim and jpegtran
# $1: Maximum quality factor for jpegoptim
jpegoptim --max=$1 --strip-all $image_path
check_success "jpegoptim"
jpegtran -optimize -progressive -copy none -outfile $compressed_image_path $image_path
check_success "jpegtran"

# Get size after optimization and compression
optimized_size=$(stat -c %s $compressed_image_path)
echo "File size after optimization and compression: $optimized_size bytes"

# Resize the image to smaller dimensions using ImageMagick
# $2: Resize dimensions (e.g., 800x600)
convert $compressed_image_path -resize $2 $compressed_image_path
check_success "ImageMagick resize"

# Get size after resizing
resized_size=$(stat -c %s $compressed_image_path)
echo "File size after resizing: $resized_size bytes"

# Function to zip the JPEG image
python3 -c "
import zopfli.gzip
with open('$compressed_image_path', 'rb') as f_in:
    data = f_in.read()
compressed_data = zopfli.gzip.compress(data)
with open('$zipped_image_path', 'wb') as f_out:
    f_out.write(compressed_data)
"
check_success "Python zipping"

# Get size after zipping
zipped_size=$(stat -c %s $zipped_image_path)
echo "File size after zipping: $zipped_size bytes"

# Function to encode the zipped JPEG image to Base64
base64 $zipped_image_path > $base64_image_path
check_success "Base64 encoding"

# Get size after Base64 encoding
base64_size=$(stat -c %s $base64_image_path)
echo "File size after Base64 encoding: $base64_size bytes"

# Cleanup other files
rm $image_path
rm $compressed_image_path
rm $zipped_image_path

echo "Optimization, compression, zipping, and Base64 encoding complete."
echo "Base64 encoded string saved to $base64_image_path"
echo "File size - $base64_size bytes"
echo "Total characters - $(awk '{ total += length($0) } END { print total }' $base64_image_path)"
