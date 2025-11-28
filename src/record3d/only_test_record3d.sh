#!/bin/bash
#単体テスト用!


# Build the image
echo "Building Docker image..."
docker build -t record3d_receiver .

# Run the container
# --privileged and -v /dev/bus/usb:/dev/bus/usb are required for USB access
# -v $(pwd)/output:/app/output maps the host output directory to the container
echo "Running Docker container..."
mkdir -p output
docker run --rm -it \
    --privileged \
    -v /dev/bus/usb:/dev/bus/usb \
    -v /var/run/usbmuxd:/var/run/usbmuxd \
    -v "$(pwd)/output:/app/output" \
    record3d_receiver
