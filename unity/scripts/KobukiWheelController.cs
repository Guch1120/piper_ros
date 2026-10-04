using System.Collections.Generic;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;

/// <summary>
/// Kobuki モバイルベースの車輪駆動コントローラ (Unity 側)。
/// </summary>
public class KobukiWheelController : MonoBehaviour
{
    [Header("Wheel Articulation Bodies")]
    [Tooltip("左車輪の ArticulationBody (wheel_left_joint / wheel_left_link)")]
    public ArticulationBody leftWheel;

    [Tooltip("右車輪の ArticulationBody (wheel_right_joint / wheel_right_link)")]
    public ArticulationBody rightWheel;

    [Header("Joint Names in ROS Message")]
    public string leftJointName = "wheel_left_joint";
    public string rightJointName = "wheel_right_joint";

    [Header("Drive Parameters")]
    [Tooltip("ドライブの減衰係数 (damping)")]
    public float damping = 2000f;
    [Tooltip("ドライブの最大トルク/力制限 (forceLimit)")]
    public float forceLimit = 2000f;

    [Header("Topic Settings")]
    [SerializeField] private string topicName = "/kobuki_unity/wheel_cmd";

    private ROSConnection ros;

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.Subscribe<JointStateMsg>(topicName, OnWheelCmdReceived);

        AutoAssignWheelsIfMissing();
        ApplyDriveSettings();
    }

    private void AutoAssignWheelsIfMissing()
    {
        if (leftWheel == null || rightWheel == null)
        {
            var bodies = GetComponentsInChildren<ArticulationBody>();
            foreach (var body in bodies)
            {
                string n = body.gameObject.name.ToLower();
                if (leftWheel == null && (n.Contains("wheel_left") || n.Contains("left_wheel")))
                {
                    leftWheel = body;
                }
                else if (rightWheel == null && (n.Contains("wheel_right") || n.Contains("right_wheel")))
                {
                    rightWheel = body;
                }
            }
        }
    }

    private void ApplyDriveSettings()
    {
        ConfigureWheelDrive(leftWheel);
        ConfigureWheelDrive(rightWheel);
    }

    private void ConfigureWheelDrive(ArticulationBody body)
    {
        if (body == null) return;

        var drive = body.xDrive;
        drive.stiffness = 0f;
        drive.damping = damping;
        drive.forceLimit = forceLimit;
        drive.targetVelocity = 0f; // 初期状態は完全停止
        drive.driveType = ArticulationDriveType.Velocity;
        body.xDrive = drive;

        body.jointFriction = 5f;
        body.angularDamping = 10f;
    }

    private void OnWheelCmdReceived(JointStateMsg msg)
    {
        if (msg == null || msg.name == null || msg.velocity == null) return;

        for (int i = 0; i < msg.name.Length && i < msg.velocity.Length; i++)
        {
            string jointName = msg.name[i];
            float targetRadPerSec = (float)msg.velocity[i];
            float targetDegPerSec = targetRadPerSec * Mathf.Rad2Deg;

            if (jointName == leftJointName && leftWheel != null)
            {
                var drive = leftWheel.xDrive;
                drive.targetVelocity = targetDegPerSec;
                leftWheel.xDrive = drive;
            }
            else if (jointName == rightJointName && rightWheel != null)
            {
                var drive = rightWheel.xDrive;
                drive.targetVelocity = targetDegPerSec;
                rightWheel.xDrive = drive;
            }
        }
    }
}
