#!/bin/bash
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

TERMINATOR_CONFIG_FILE="$WORKSPACE_DIR/.config/terminator/config"
TERMINATOR_LAYOUT_FILE="$WORKSPACE_DIR/.config/terminator/terminator_layout"

# DBus
if command -v service >/dev/null 2>&1; then
    echo "Starting DBus service inside container..."
    service dbus start >/dev/null 2>&1 || true
fi

cleanup_ros_nodes() {
    if command -v ros2 >/dev/null 2>&1; then
        ros2 node list 2>/dev/null | grep -v '/_ros2cli' | xargs -r ros2 node kill || true
    fi
    echo "Cleaned up ROS nodes in container."
}
trap cleanup_ros_nodes EXIT

# ROS setup scripts are not always nounset-safe
set +u
if [ -f /opt/ros/humble/setup.bash ]; then
    echo "RUN: source /opt/ros/humble/setup.bash"
    source /opt/ros/humble/setup.bash
    echo "OK."
fi

if [ -f "$WORKSPACE_DIR/install/setup.bash" ]; then
    echo "RUN: source $WORKSPACE_DIR/install/setup.bash"
    source "$WORKSPACE_DIR/install/setup.bash"
    echo "OK."
fi
set -u

if [ ! -f "$TERMINATOR_LAYOUT_FILE" ]; then
    echo "Error: Terminator layout file not found: $TERMINATOR_LAYOUT_FILE" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$TERMINATOR_LAYOUT_FILE"

if [ -z "${layout:-}" ]; then
    echo "Error: layout is not defined in $TERMINATOR_LAYOUT_FILE" >&2
    exit 1
fi

if [ ! -f "$TERMINATOR_CONFIG_FILE" ]; then
    echo "Error: Terminator config not found: $TERMINATOR_CONFIG_FILE" >&2
    exit 1
fi

cd "$WORKSPACE_DIR"
echo "WORKSPACE_DIR=$WORKSPACE_DIR"
echo "Using Terminator layout: $layout"

exec terminator -m -g "$TERMINATOR_CONFIG_FILE" -l "$layout"
