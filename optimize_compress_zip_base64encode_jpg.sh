#!/bin/bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [-q quality] [-r resize] [-s snapshot_url] [-o output_file]

    -q quality       Maximum JPEG quality for jpegoptim (default: 75)
    -r resize        Resize dimensions (e.g., 800x600; default: 800x600)
    -s snapshot_url  URL to trigger snapshot capture (default: http://localhost:8080/0/action/snapshot)
    -o output_file   Output file path for Base64 encoded image (default: base64_image.gz)
EOF
  exit 1
}

# Set default values
quality=75
resize="800x600"
snapshot_url="http://localhost:8080/0/action/snapshot"
output_file="base64_image.gz"

# Parse options
while getopts "q:r:s:o:h" opt; do
  case "$opt" in
    q) quality="$OPTARG" ;;
    r) resize="$OPTARG" ;;
    s) snapshot_url="$OPTARG" ;;
    o) output_file="$OPTARG" ;;
    h) usage ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

# Define intermediate file names (can be parameterized further if needed)
image_path="lastsnap.jpg"
compressed_image_path="compressed.jpg"
zipped_image_path="compressed_image.gz"

# Function to check command success
check_success() {
  if [ $? -ne 0 ]; then
    echo "Error: $1 failed." >&2
    exit 1
  fi
}

echo "Capturing snapshot from $snapshot_url..."
curl -s "$snapshot_url" > /dev/null
check_success "Snapshot capture"

# Give Motion a second to write the snapshot
sleep 1

# Copy the snapshot image from Motion’s directory to current directory
cp /var/lib/motion/lastsnap.jpg ./
check_success "Copy snapshot"

# Cleanup old snapshots in Motion’s directory
sudo rm -f /var/lib/motion/*
check_success "Remove old snapshots"

initial_size=$(stat -c %s "$image_path")
echo "Initial file size: $initial_size bytes"

echo "Optimizing JPEG using quality factor $quality..."
jpegoptim --max="$quality" --strip-all "$image_path"
check_success "jpegoptim"

jpegtran -optimize -progressive -copy none -outfile "$compressed_image_path" "$image_path"
check_success "jpegtran"

optimized_size=$(stat -c %s "$compressed_image_path")
echo "File size after optimization and compression: $optimized_size bytes"

echo "Resizing image to $resize..."
convert "$compressed_image_path" -resize "$resize" "$compressed_image_path"
check_success "ImageMagick resize"

resized_size=$(stat -c %s "$compressed_image_path")
echo "File size after resizing: $resized_size bytes"

echo "Compressing image using Python Zopfli..."
python3 - <<EOF
import zopfli.gzip
with open("$compressed_image_path", "rb") as f_in:
    data = f_in.read()
compressed_data = zopfli.gzip.compress(data)
with open("$zipped_image_path", "wb") as f_out:
    f_out.write(compressed_data)
EOF
check_success "Python zipping"

zipped_size=$(stat -c %s "$zipped_image_path")
echo "File size after zipping: $zipped_size bytes"

echo "Encoding zipped image to Base64..."
base64 "$zipped_image_path" > "$output_file"
check_success "Base64 encoding"

base64_size=$(stat -c %s "$output_file")
echo "File size after Base64 encoding: $base64_size bytes"

char_count=$(awk '{ total += length($0) } END { print total }' "$output_file")
echo "Total characters in Base64 encoded file: $char_count"

# Cleanup intermediate files
rm -f "$image_path" "$compressed_image_path" "$zipped_image_path"

echo "Optimization, compression, zipping, and Base64 encoding complete."
echo "Base64 encoded string saved to: $output_file"
echo "Final file size: $base64_size bytes"
