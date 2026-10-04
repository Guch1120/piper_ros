#!/usr/bin/env bash

# Colors
CYAN='\033[0;36m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Trap Ctrl+C (SIGINT) to prevent script exit, just restart loop
trap 'echo -e "\n${YELLOW}Interrupted. Press Enter to restart...${NC}";' SIGINT

# ------------------------------------------------------------
# Detect script directory
# ------------------------------------------------------------
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------
# Optional ROS environment setup
#
# ROSがあるコンテナではsourceする。
# ROSがないコンテナではwarningではなくINFO扱いでスキップする。
# ------------------------------------------------------------
ROS_ENABLED=false

# ROS 2 Humble
if [ -f "/opt/ros/humble/setup.bash" ]; then
    echo -e "${BLUE}[INFO] ROS 2 Humble detected. Sourcing /opt/ros/humble/setup.bash${NC}"
    source /opt/ros/humble/setup.bash
    ROS_ENABLED=true

# ROS 2 Jazzyなど、将来別ディストリも一応拾いたい場合
elif [ -d "/opt/ros" ] && compgen -G "/opt/ros/*/setup.bash" > /dev/null; then
    ROS_SETUP="$(ls -d /opt/ros/*/setup.bash | head -n 1)"
    echo -e "${BLUE}[INFO] ROS detected. Sourcing $ROS_SETUP${NC}"
    source "$ROS_SETUP"
    ROS_ENABLED=true

else
    echo -e "${YELLOW}[INFO] ROS environment not found. Running as non-ROS command wrapper.${NC}"
fi

# ------------------------------------------------------------
# Optional workspace setup
#
# ROSが有効な場合だけ install/setup.bash をsourceする。
# 非ROSコンテナでは不要なので探さない。
# ------------------------------------------------------------
if [ "$ROS_ENABLED" = true ]; then
    if [ -f "$DIR/install/setup.bash" ]; then
        echo -e "${BLUE}[INFO] Sourcing workspace: $DIR/install/setup.bash${NC}"
        source "$DIR/install/setup.bash"
    else
        echo -e "${YELLOW}[INFO] Workspace setup not found: $DIR/install/setup.bash${NC}"
        echo -e "${YELLOW}[INFO] Skip workspace source. If this is a ROS workspace, run colcon build first.${NC}"
    fi
fi

# ------------------------------------------------------------
# Check command
# ------------------------------------------------------------
if [ $# -eq 0 ]; then
    echo -e "${RED}[ERROR] No command specified.${NC}"
    echo "Usage:"
    echo "  bash $0 <command> [args...]"
    echo
    echo "Examples:"
    echo "  bash $0 ros2 topic list"
    echo "  bash $0 python3 --version"
    echo "  bash $0 bash can_activate.sh can0 1000000"
    exit 1
fi

# ------------------------------------------------------------
# Interactive loop
# ------------------------------------------------------------
while true; do
    echo -e "==================================================="
    if [ "$ROS_ENABLED" = true ]; then
        echo -e "Mode: ${GREEN}ROS-enabled container${NC}"
    else
        echo -e "Mode: ${YELLOW}non-ROS container${NC}"
    fi

    echo -e "Command to run:"
    printf "${CYAN}"
    printf '%q ' "$@"
    printf "${NC}\n"

    echo -e "==================================================="
    echo -e "Press ${GREEN}Enter${NC} to execute, or ${RED}'q' then Enter${NC} to quit."

    read -r input
    if [[ "$input" == "q" ]]; then
        echo "Exiting..."
        exit 0
    fi

    echo -e "Executing..."
    echo -e "---------------------------------------------------"

    # Check if command exists
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}Error: Command '$1' not found in PATH.${NC}"
        echo -e "PATH is: $PATH"
    else
        "$@"
        EXIT_CODE=$?

        echo -e "---------------------------------------------------"
        if [ $EXIT_CODE -ne 0 ]; then
            echo -e "${RED}Command finished with error code: $EXIT_CODE${NC}"
        else
            echo -e "${GREEN}Command finished successfully.${NC}"
        fi
    fi

    echo ""
done