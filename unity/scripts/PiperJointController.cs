using System.Collections.Generic;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;

/// <summary>
/// Piper アームの関節駆動コントローラ (Unity 側)。
/// 
/// 完全静止・即時初期化設計:
///   1. Awake() / Start() で全コライダーの自己衝突を無効化。
///   2. コルーチン待機を完全に撤廃し、1フレーム目から全関節の driveType = Target, target = 0, stiffness/damping を即時同期適用。
///   3. useGravity = false で重力落下を完全防止。
/// </summary>
public class PiperJointController : MonoBehaviour
{
    [Header("Joint Bodies (joint1 to joint7 in order)")]
    public ArticulationBody[] joints;

    [Header("PD Drive Settings")]
    [Tooltip("関節の保持剛性 (Stiffness)")]
    public float stiffness  = 20000f;
    [Tooltip("関節の減衰 (Damping)")]
    public float damping    = 1000f;
    [Tooltip("最大トルク制限 (Force Limit)")]
    public float forceLimit = 2000f;

    private ROSConnection ros;
    private const string CmdTopic = "/piper_unity/joint_cmd";

    void Awake()
    {
        // 1. ロボット内部パーツ同士の自己衝突を無効化（めり込み反発力を排除）
        IgnoreSelfCollisions();

        // 2. 関節の自動検索
        if (joints == null || joints.Length == 0)
        {
            AutoAssignJointsIfMissing();
        }

        // 3. 1フレーム目から即座に初期姿勢を固定
        LockAllJointsImmediately();
    }

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.Subscribe<JointStateMsg>(CmdTopic, OnJointCmd);
    }

    private void IgnoreSelfCollisions()
    {
        var colliders = GetComponentsInChildren<Collider>();
        for (int i = 0; i < colliders.Length; i++)
        {
            for (int j = i + 1; j < colliders.Length; j++)
            {
                Physics.IgnoreCollision(colliders[i], colliders[j], true);
            }
        }
    }

    private void LockAllJointsImmediately()
    {
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
            drive.target     = 0f; // 初期ゼロ位置に即座に固定
            drive.targetVelocity = 0f;
            body.xDrive = drive;

            // 速度のリセット
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
