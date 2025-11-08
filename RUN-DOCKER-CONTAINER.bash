#!/bin/bash

DOCKER_COMPOSE_PATH="./docker/docker-compose.yml"
DOCKER_CONTAINER_NAME="piper-humble-dev"
ON_ENTER_CONTAINER_SCRIPT="./docker/scripts/initialize-docker-container.bash"
KILL_ROS_NODES_SCRIPT="./docker/scripts/kill-ros-nodes.bash"

xhost +local:docker

if docker ps | grep -q "$DOCKER_CONTAINER_NAME"; then
    echo "$DOCKER_CONTAINER_NAME コンテナは既に起動中"
else
    echo "$DOCKER_CONTAINER_NAME コンテナを起動"
    docker compose -f $DOCKER_COMPOSE_PATH up -d $DOCKER_CONTAINER_NAME
fi

# コンテナ内でTerminatorを起動し、終了処理を行うスクリプトを実行
# -it オプションでインタラクティブなセッションを確保することが重要
echo "コンテナ内でTerminatorを起動します..."
docker compose -f $DOCKER_COMPOSE_PATH exec -it $DOCKER_CONTAINER_NAME $ON_ENTER_CONTAINER_SCRIPT