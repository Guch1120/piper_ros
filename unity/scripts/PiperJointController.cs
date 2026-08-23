using System.Collections.Generic;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;

/// <summary>
/// Piper アームの関節駆動コントローラ (Unity 側)。
/// 
/// 制御方式:
///   1. Start() で各 ArticulationBody の xDrive に適切な剛性 (stiffness)・減衰 (damping)・driveType=Target を設定
///   2. ROS 2 (/piper_unity/joint_cmd) からの JointStateMsg 受信時に drive.target を更新し、PD サーボ制御でスムーズに駆動
/// </summary>
public class PiperJointController : MonoBehaviour
{
    [Header("Joint Bodies (joint1 to joint7 in order)")]
    public ArticulationBody[] joints;

    [Header("PD Drive Settings")]
    [Tooltip("関節の保持剛性 (Stiffness)")]
    public float stiffness  = 50000f;
    [Tooltip("関節の減衰 (Damping)")]
    public float damping    = 2000f;
    [Tooltip("最大トルク制限 (Force Limit)")]
    public float forceLimit = 5000f;

    private ROSConnection ros;
    private const string CmdTopic = "/piper_unity/joint_cmd";

    void Awake()
    {
        AutoAssignJointsIfMissing();
    }

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.Subscribe<JointStateMsg>(CmdTopic, OnJointCmd);

        AutoAssignJointsIfMissing();
        ApplyDriveSettingsToAllJoints();
    }

    public void ApplyDriveSettingsToAllJoints()
    {
        if (joints == null || joints.Length == 0)
        {
            AutoAssignJointsIfMissing();
        }

        if (joints == null) return;

        for (int i = 0; i < joints.Length; i++)
        {
            var body = joints[i];
            if (body == null) continue;

            body.useGravity = false;
            body.angularDamping = 10f;
            body.linearDamping = 10f;
            body.jointFriction = 5f;

            var drive = body.xDrive;
            drive.stiffness  = stiffness;
            drive.damping    = damping;
            drive.forceLimit = forceLimit;
            drive.driveType  = ArticulationDriveType.Target;
            drive.targetVelocity = 0f;
            body.xDrive = drive;

            if (body.dofCount > 0)
            {
                body.jointVelocity = new ArticulationReducedSpace(0f);
                body.jointForce = new ArticulationReducedSpace(0f);
            }
        }
    }

    private void AutoAssignJointsIfMissing()
    {
        var bodies = GetComponentsInChildren<ArticulationBody>();
        var armJointMap = new Dictionary<int, ArticulationBody>();

        foreach (var body in bodies)
        {
            string n = body.gameObject.name.ToLower();
            for (int i = 1; i <= 8; i++)
            {
                if (n == $"link{i}" || n.EndsWith($"/link{i}") || n.Contains($"link{i}"))
                {
                    if (!armJointMap.ContainsKey(i))
                        armJointMap[i] = body;
                }
            }
        }

        List<ArticulationBody> list = new List<ArticulationBody>();
        for (int i = 1; i <= 7; i++)
        {
            if (armJointMap.ContainsKey(i))
                list.Add(armJointMap[i]);
        }
        if (list.Count > 0)
            joints = list.ToArray();
    }

    void OnJointCmd(JointStateMsg msg)
    {
        if (joints == null || joints.Length == 0) return;

        var nameToIdx = new Dictionary<string, int>(joints.Length);
        for (int i = 0; i < joints.Length; i++)
            nameToIdx[$"joint{i + 1}"] = i;

        for (int k = 0; k < msg.name.Length && k < msg.position.Length; k++)
        {
            if (!nameToIdx.TryGetValue(msg.name[k], out int idx)) continue;
            if (idx >= joints.Length || joints[idx] == null) continue;

            var body  = joints[idx];
            var drive = body.xDrive;

            drive.target = body.jointType == ArticulationJointType.RevoluteJoint
                ? (float)(msg.position[k] * Mathf.Rad2Deg)
                : (float)msg.position[k];

            body.xDrive = drive;
        }
    }
}
