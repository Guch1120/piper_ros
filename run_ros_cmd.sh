#!/bin/bash

# Colors
CYAN='\033[0;36m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

trap 'echo -e "\n${YELLOW}Interrupted. Press Enter to restart...${NC}";' SIGINT

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

source_ros_env() {
    if [ -f "/opt/ros/humble/setup.bash" ]; then
        source /opt/ros/humble/setup.bash
    else
        echo -e "${RED}Warning: /opt/ros/humble/setup.bash not found.${NC}"
    fi

    if [ -f "$DIR/install/setup.bash" ]; then
        source "$DIR/install/setup.bash"
    else
        echo -e "${YELLOW}Warning: $DIR/install/setup.bash not found. Did you run 'colcon build'?${NC}"
    fi

    # bash のコマンドキャッシュ更新
    hash -r
}

# 初回もsource
source_ros_env

while true; do
    echo -e "==================================================="
    echo -e "Command to run:"
    echo -e "${CYAN}$@${NC}"
    echo -e "==================================================="
    echo -e "Press ${GREEN}Enter${NC} to execute, or ${RED}'q' then Enter${NC} to quit."

    read -r input
    if [[ "$input" == "q" ]]; then
        echo "Exiting..."
        exit 0
    fi

    echo -e "Executing..."
    echo -e "---------------------------------------------------"

    # 毎回実行直前にsourceし直す
    source_ros_env

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