#!/usr/bin/env python3

# ROSメッセージをpublishするノード
import rospy
from std_msgs.msg import String

def main():
    rospy.init_node("test_publisher", anonymous=True)
    pub = rospy.Publisher("/test/message", String, queue_size=1)
    rate = rospy.Rate(1)  # 1Hz（1秒に1回）

    count = 0
    while not rospy.is_shutdown():
        msg = String()
        msg.data = f"Hello from ROS! count={count}"
        pub.publish(msg)
        rospy.loginfo(f"[Publisher] 送信: {msg.data}")
        count += 1
        rate.sleep()

if __name__ == "__main__":
    main()
