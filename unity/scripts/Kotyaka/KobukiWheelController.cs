using System.Collections.Generic;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;

/// <summary>
/// Kobuki モバイルベースの車輪駆動コントローラ & 走行安定化 (Unity 側)。
/// 
/// 転倒防止・走行安定化:
///   1. base_link の質量 (15kg) と重心を下げて低重心バラスト化
///   2. カチャカシェルフの脚キャスターおよび前後のキャスターに低摩擦マテリアルを設定 (引っかかり・転倒防止)
///   3. 主輪に適切なグリップマテリアルを設定
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

    [Header("Stability Settings")]
    [Tooltip("base_link のバラスト質量 (kg)")]
    public float baseMass = 15.0f;
    [Tooltip("base_link の重心オフセット (Y軸を下げる)")]
    public Vector3 baseCenterOfMass = new Vector3(0f, -0.05f, 0f);

    [Header("Topic Settings")]
    [SerializeField] private string topicName = "/kobuki_unity/wheel_cmd";

    private ROSConnection ros;

    void Awake()
    {
        AutoAssignWheelsIfMissing();
        StabilizeBaseAndColliders();
    }

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.Subscribe<JointStateMsg>(topicName, OnWheelCmdReceived);

        AutoAssignWheelsIfMissing();
        ApplyDriveSettings();
        StabilizeBaseAndColliders();
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

    private void StabilizeBaseAndColliders()
    {
        // 1. base_link の低重心バラスト化
        var bodies = GetComponentsInChildren<ArticulationBody>();
        foreach (var body in bodies)
        {
            string n = body.gameObject.name.ToLower();
            if (n == "base_link" || n.EndsWith("/base_link"))
            {
                body.mass = baseMass;
                body.centerOfMass = baseCenterOfMass;
                body.angularDamping = 10f;
                body.linearDamping = 5f;
            }
        }

        // 2. フィジックスマテリアルの生成
        var frictionlessMat = new PhysicsMaterial("FrictionlessCaster")
        {
            staticFriction = 0.0f,
            dynamicFriction = 0.0f,
            frictionCombine = PhysicsMaterialCombine.Minimum,
            bounciness = 0.0f,
            bounceCombine = PhysicsMaterialCombine.Minimum
        };

        var wheelGripMat = new PhysicsMaterial("WheelGrip")
        {
            staticFriction = 1.0f,
            dynamicFriction = 0.8f,
            frictionCombine = PhysicsMaterialCombine.Maximum,
            bounciness = 0.0f,
            bounceCombine = PhysicsMaterialCombine.Minimum
        };

        // 3. キャスター・シェルフ・主輪へのマテリアル適用
        var colliders = GetComponentsInChildren<Collider>();
        foreach (var col in colliders)
        {
            string n = col.gameObject.name.ToLower();
            string parentName = col.transform.parent != null ? col.transform.parent.name.ToLower() : "";

            // 主輪コライダー
            if (n.Contains("wheel_left") || n.Contains("wheel_right") || parentName.Contains("wheel"))
            {
                col.material = wheelGripMat;
            }
            // キャスターまたはシェルフの脚（引っかかり防止）
            else if (n.Contains("caster") || n.Contains("shelf") || parentName.Contains("caster") || parentName.Contains("shelf"))
            {
                col.material = frictionlessMat;
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
