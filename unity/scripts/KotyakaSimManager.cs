using UnityEngine;
using Unity.Robotics.ROSTCPConnector;

/// <summary>
/// コチャカ (Kobuki + カチャカシェルフ + Piper) 統合シミュレーション管理コンポーネント (Unity 側)。
/// シーン内の各コンポーネントへの参照を束ね、初期化や状態確認を支援します。
/// </summary>
public class KotyakaSimManager : MonoBehaviour
{
    [Header("Components")]
    public KobukiWheelController wheelController;
    public KobukiWheelStatePublisher wheelPublisher;
    public PiperJointController armController;
    public PiperJointStatePublisher armPublisher;
    public RealSenseCameraPublisher cameraPublisher;

    void Awake()
    {
        // ROSConnection のインスタンスを初期化（Unity の Robotics 設定を使用）
        var ros = ROSConnection.GetOrCreateInstance();

        // 未設定のコンポーネントを自動取得
        if (wheelController == null) wheelController = GetComponentInChildren<KobukiWheelController>();
        if (wheelPublisher == null) wheelPublisher = GetComponentInChildren<KobukiWheelStatePublisher>();
        if (armController == null) armController = GetComponentInChildren<PiperJointController>();
        if (armPublisher == null) armPublisher = GetComponentInChildren<PiperJointStatePublisher>();
        if (cameraPublisher == null) cameraPublisher = GetComponentInChildren<RealSenseCameraPublisher>();
    }
}
