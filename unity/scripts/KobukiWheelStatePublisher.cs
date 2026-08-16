using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;
using RosMessageTypes.Std;

/// <summary>
/// Kobuki モバイルベースの車輪状態パブリッシャー (Unity 側)。
/// 左右の車輪 (ArticulationBody) の回転角 (rad, 連続値) および角速度 (rad/s) を取得し、
/// ROS 側の /kobuki_unity/wheel_states (JointStateMsg) に定期送信します。
/// </summary>
public class KobukiWheelStatePublisher : MonoBehaviour
{
    [Header("Wheel Articulation Bodies")]
    [Tooltip("左車輪の ArticulationBody (wheel_left_joint / wheel_left_link)")]
    public ArticulationBody leftWheel;

    [Tooltip("右車輪の ArticulationBody (wheel_right_joint / wheel_right_link)")]
    public ArticulationBody rightWheel;

    [Header("Joint Names in ROS Message")]
    public string leftJointName = "wheel_left_joint";
    public string rightJointName = "wheel_right_joint";

    [Header("Publish Settings")]
    [Tooltip("Publish周波数 (Hz)")]
    public float publishHz = 50f;

    [Header("Topic Settings")]
    [SerializeField] private string topicName = "/kobuki_unity/wheel_states";

    private ROSConnection ros;
    private double leftCumulativePos = 0.0;
    private double rightCumulativePos = 0.0;
    private float prevLeftRawAngle = 0f;
    private float prevRightRawAngle = 0f;
    private bool isFirstUpdate = true;

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.RegisterPublisher<JointStateMsg>(topicName);

        AutoAssignWheelsIfMissing();

        if (leftWheel != null && leftWheel.dofCount > 0)
            prevLeftRawAngle = leftWheel.jointPosition[0];
        if (rightWheel != null && rightWheel.dofCount > 0)
            prevRightRawAngle = rightWheel.jointPosition[0];

        InvokeRepeating(nameof(PublishWheelStates), 0f, 1f / publishHz);
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

    private void UpdateCumulativePosition()
    {
        if (leftWheel != null && leftWheel.dofCount > 0)
        {
            float currentLeft = leftWheel.jointPosition[0];
            if (!isFirstUpdate)
            {
                float delta = Mathf.DeltaAngle(prevLeftRawAngle * Mathf.Rad2Deg, currentLeft * Mathf.Rad2Deg) * Mathf.Deg2Rad;
                leftCumulativePos += delta;
            }
            prevLeftRawAngle = currentLeft;
        }

        if (rightWheel != null && rightWheel.dofCount > 0)
        {
            float currentRight = rightWheel.jointPosition[0];
            if (!isFirstUpdate)
            {
                float delta = Mathf.DeltaAngle(prevRightRawAngle * Mathf.Rad2Deg, currentRight * Mathf.Rad2Deg) * Mathf.Deg2Rad;
                rightCumulativePos += delta;
            }
            prevRightRawAngle = currentRight;
        }

        isFirstUpdate = false;
    }

    private void FixedUpdate()
    {
        UpdateCumulativePosition();
    }

    void PublishWheelStates()
    {
        double leftVel = 0.0;
        double rightVel = 0.0;

        if (leftWheel != null && leftWheel.dofCount > 0)
        {
            leftVel = leftWheel.jointVelocity[0];
        }
        if (rightWheel != null && rightWheel.dofCount > 0)
        {
            rightVel = rightWheel.jointVelocity[0];
        }

        float timeNow = Time.realtimeSinceStartup;
        int sec = (int)timeNow;
        uint nanosec = (uint)((timeNow - sec) * 1e9);

        var msg = new JointStateMsg
        {
            header = new HeaderMsg
            {
                stamp = new RosMessageTypes.BuiltinInterfaces.TimeMsg
                {
                    sec = sec,
                    nanosec = nanosec
                },
                frame_id = ""
            },
            name = new string[] { leftJointName, rightJointName },
            position = new double[] { leftCumulativePos, rightCumulativePos },
            velocity = new double[] { leftVel, rightVel },
            effort = new double[] { 0.0, 0.0 }
        };

        ros.Publish(topicName, msg);
    }
}
