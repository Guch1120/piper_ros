using System.Collections.Generic;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;

/// <summary>
/// Piper 6軸アーム + グリッパーの関節コントローラ (Unity 側)。
/// ROS 側の /piper_unity/joint_cmd (JointStateMsg) を購読し、
/// 各関節 (link1〜link7 の ArticulationBody) の目標位置 (xDrive.target) を更新します。
/// </summary>
public class PiperJointController : MonoBehaviour
{
    [Header("Joint Bodies (joint1 to joint7 の順)")]
    [Tooltip("Inspector で link1〜link6 (アーム) および link7 (グリッパー) を順にアサイン")]
    public ArticulationBody[] joints;

    [Header("Drive Settings")]
    public float stiffness = 100000f;
    public float damping = 10000f;
    public float forceLimit = 10000f;

    [Header("Topic Settings")]
    [SerializeField] private string topicName = "/piper_unity/joint_cmd";

    private ROSConnection ros;

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.Subscribe<JointStateMsg>(topicName, OnJointCmd);
        ApplyDriveSettings();
    }

    void OnJointCmd(JointStateMsg msg)
    {
        if (msg == null || msg.name == null || msg.position == null || joints == null) return;

        var nameToIndex = new Dictionary<string, int>();
        for (int i = 0; i < joints.Length; i++)
            nameToIndex[$"joint{i + 1}"] = i;

        for (int k = 0; k < msg.name.Length && k < msg.position.Length; k++)
        {
            if (!nameToIndex.TryGetValue(msg.name[k], out int idx)) continue;
            if (idx >= joints.Length || joints[idx] == null) continue;

            var body = joints[idx];
            var drive = body.xDrive;

            // revolute (joint1..6): rad → deg, prismatic (joint7 gripper): m のまま
            if (body.jointType == ArticulationJointType.RevoluteJoint)
                drive.target = (float)(msg.position[k] * Mathf.Rad2Deg);
            else
                drive.target = (float)msg.position[k];

            body.xDrive = drive;
        }
    }

    public void ApplyDriveSettings()
    {
        if (joints == null) return;

        foreach (var body in joints)
        {
            if (body == null) continue;
            var drive = body.xDrive;
            drive.stiffness = stiffness;
            drive.damping = damping;
            drive.forceLimit = forceLimit;
            drive.driveType = ArticulationDriveType.Target;
            body.xDrive = drive;
        }
    }
}
