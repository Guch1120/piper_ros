"""VLM Supervisor ROS 1 (Noetic) node. 未実装.

core/ は共通. rospy 版の ObservationAdapter / FlexBEAdapter をここに実装する.
ros1_bridge は使用しない. Noetic 環境で `rostopic list | grep flexbe` 等を確認してから着手する.
"""


def main():
    raise NotImplementedError("ROS1 adapter is not implemented yet")


if __name__ == "__main__":
    main()
