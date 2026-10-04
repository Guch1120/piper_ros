using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;
using RosMessageTypes.Std;

/// <summary>
/// Piper 6軸アーム + グリッパーの関節状態パブリッシャー (Unity 側)。
/// 各関節 (link1〜link7 の ArticulationBody) の状態を取得し、
/// ROS 側の /piper_unity/joint_states (JointStateMsg) に定期送信します。
/// </summary>
public class PiperJointStatePublisher : MonoBehaviour
{
    [Header("Joint Bodies (joint1 to joint7 の順)")]
    [Tooltip("Inspector で link1〜link6 (アーム) および link7 (グリッパー) を順にアサイン")]
    public ArticulationBody[] joints;

    [Header("Publish Rate (Hz)")]
    public float publishHz = 50f;

    [Header("Topic Settings")]
    [SerializeField] private string topicName = "/piper_unity/joint_states";

    private ROSConnection ros;
    private static readonly string[] JointNames =
        { "joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7" };

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.RegisterPublisher<JointStateMsg>(topicName);
        InvokeRepeating(nameof(PublishJointStates), 0f, 1f / publishHz);
    }

    void PublishJointStates()
    {
        if (joints == null) return;

        int n = Mathf.Min(joints.Length, JointNames.Length);
        double[] positions = new double[n];
        double[] velocities = new double[n];
        double[] efforts = new double[n];

        for (int i = 0; i < n; i++)
        {
            if (joints[i] == null || joints[i].dofCount == 0) continue;
            // revolute: rad, prismatic: m (ArticulationBody.jointPosition は rad / m)
            positions[i] = joints[i].jointPosition[0];
            velocities[i] = joints[i].jointVelocity[0];
            efforts[i] = joints[i].jointForce[0];
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
            name = JointNames[..n],
            position = positions,
            velocity = velocities,
            effort = efforts
        };

        ros.Publish(topicName, msg);
    }
}
