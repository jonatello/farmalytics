#!/bin/bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: $0 [-i input_file] [-z zipped_file] [-r restored_file] [-P python_cmd] [-B base64_cmd] [-h]

Options:
  -i input_file    Input file path for Base64 encoded image (default: combined_message.log)
  -z zipped_file   Temporary zipped file path (default: compressed_image.gz)
  -r restored_file Restored image output path (default: restored.jpg)
  -P python_cmd    Python command to use (default: python3)
  -B base64_cmd    Base64 command to use (default: base64)
  -h               Show this help message.
EOF
  exit 1
}

# Set default values
input_file="combined_message.log"
zipped_file="compressed_image.gz"
restored_file="restored.jpg"
python_cmd="python3"
base64_cmd="base64"

while getopts "i:z:r:P:B:h" opt; do
  case "$opt" in
    i) input_file="$OPTARG" ;;
    z) zipped_file="$OPTARG" ;;
    r) restored_file="$OPTARG" ;;
    P) python_cmd="$OPTARG" ;;
    B) base64_cmd="$OPTARG" ;;
    h) usage ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

check_success() {
  if [ $? -ne 0 ]; then
    echo "Error: $1 failed." >&2
    exit 1
  fi
}

echo "Decoding Base64 from '$input_file'..."
$base64_cmd -d "$input_file" > "$zipped_file"
check_success "Base64 decoding"

echo "Unzipping using Python ($python_cmd)..."
$python_cmd -c "
import gzip
with open('$zipped_file', 'rb') as f_in:
    compressed_data = f_in.read()
data = gzip.decompress(compressed_data)
with open('$restored_file', 'wb') as f_out:
    f_out.write(data)
"
check_success "Python unzipping"

rm -f "$zipped_file"

restored_size=$(stat -c %s "$restored_file")
echo "Restored image size: $restored_size bytes"

echo "Base64 decoding, unzipping, and restoration complete."
echo "Restored image saved to: $restored_file"
