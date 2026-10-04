#if UNITY_EDITOR
using System.IO;
using System.Collections.Generic;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using Unity.Robotics.ROSTCPConnector;

/// <summary>
/// Unity エディタ用 コチャカ統合シミュレーションシーン自動生成・セットアップスクリプト。
/// </summary>
public class KotyakaSceneBuilder : EditorWindow
{
    [MenuItem("Kotyaka/Create Kotyaka Simulation Scene")]
    public static void CreateKotyakaScene()
    {
        var newScene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        // 照明 (Directional Light)
        GameObject lightGo = new GameObject("Directional Light");
        Light light = lightGo.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.0f;
        light.color = Color.white;
        lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        // 環境床面 (Ground Plane)
        GameObject plane = GameObject.CreatePrimitive(PrimitiveType.Plane);
        plane.name = "Ground";
        plane.transform.position = Vector3.zero;
        plane.transform.localScale = new Vector3(10f, 1f, 10f);
        var renderer = plane.GetComponent<MeshRenderer>();
        if (renderer != null)
        {
            var mat = new Material(Shader.Find("Standard"));
            mat.color = new Color(0.3f, 0.35f, 0.4f);
            renderer.material = mat;
        }

        // ROS Connection
        GameObject rosGo = new GameObject("ROSConnection");
        rosGo.AddComponent<ROSConnection>();

        // シーン確認用メインカメラ (Main Camera -> Display 1)
        GameObject mainCamGo = new GameObject("Main Camera");
        var mainCam = mainCamGo.AddComponent<Camera>();
        mainCam.tag = "MainCamera";
        mainCam.targetDisplay = 0;
        mainCamGo.AddComponent<AudioListener>();
        mainCamGo.transform.position = new Vector3(1.5f, 1.2f, -1.8f);
        mainCamGo.transform.rotation = Quaternion.Euler(25f, -35f, 0f);

        // シーン保存
        string scenesDir = "Assets/Scenes";
        if (!AssetDatabase.IsValidFolder(scenesDir))
        {
            AssetDatabase.CreateFolder("Assets", "Scenes");
        }
        string scenePath = Path.Combine(scenesDir, "KotyakaSimulation.unity");
        EditorSceneManager.SaveScene(newScene, scenePath);
        AssetDatabase.Refresh();

        EditorUtility.DisplayDialog(
            "Kotyaka Scene Created",
            $"コチャカシミュレーションシーンが作成されました:\n{scenePath}\n\n" +
            "【次の操作】\n" +
            "1. Assets > URDF > mobile_manipulator > mobile_manipulator.urdf を右クリックしてインポート\n" +
            "   (Select Axis Type: Y Axis, Convex Decomposer: Unity)\n" +
            "2. Hierarchy でインポートされた mobile_manipulator を選択し、\n" +
            "   [Kotyaka] -> [Setup Components on Selected Robot] を実行してください。",
            "OK"
        );
    }

    [MenuItem("Kotyaka/Setup Components on Selected Robot")]
    public static void SetupSelectedRobot()
    {
        var selected = Selection.activeGameObject;
        if (selected == null)
        {
            selected = GameObject.Find("mobile_manipulator");
            if (selected == null)
            {
                EditorUtility.DisplayDialog("エラー", "Hierarchy 上でインポートしたロボット (mobile_manipulator) を選択してください。", "OK");
                return;
            }
        }

        // 不要な空の Kotyaka_Robot を削除
        var allGos = GameObject.FindObjectsByType<GameObject>(FindObjectsSortMode.None);
        foreach (var go in allGos)
        {
            if (go != selected && go.name == "Kotyaka_Robot" && go.transform.childCount == 0)
            {
                DestroyImmediate(go);
            }
        }

        SetupRobotComponents(selected);
        EditorUtility.DisplayDialog("完了", $"『{selected.name}』の完全静止・自己干渉防止・コントローラ・カメラ設定が完了しました！", "OK");
    }

    private static void SetupRobotComponents(GameObject robotRoot)
    {
        var simManager = robotRoot.GetComponent<KotyakaSimManager>();
        if (simManager == null) simManager = robotRoot.AddComponent<KotyakaSimManager>();

        var wheelCtrl = robotRoot.GetComponent<KobukiWheelController>();
        if (wheelCtrl == null) wheelCtrl = robotRoot.AddComponent<KobukiWheelController>();

        var wheelPub = robotRoot.GetComponent<KobukiWheelStatePublisher>();
        if (wheelPub == null) wheelPub = robotRoot.AddComponent<KobukiWheelStatePublisher>();

        var armCtrl = robotRoot.GetComponent<PiperJointController>();
        if (armCtrl == null) armCtrl = robotRoot.AddComponent<PiperJointController>();

        var armPub = robotRoot.GetComponent<PiperJointStatePublisher>();
        if (armPub == null) armPub = robotRoot.AddComponent<PiperJointStatePublisher>();

        var bodies = robotRoot.GetComponentsInChildren<ArticulationBody>();
        ArticulationBody leftWheel = null;
        ArticulationBody rightWheel = null;
        
        var armJointMap = new Dictionary<int, ArticulationBody>();

        foreach (var body in bodies)
        {
            string n = body.gameObject.name.ToLower();
            if (n.Contains("wheel_left") || n.Contains("left_wheel"))
                leftWheel = body;
            else if (n.Contains("wheel_right") || n.Contains("right_wheel"))
                rightWheel = body;

            for (int i = 1; i <= 8; i++)
            {
                if (n == $"link{i}" || n.EndsWith($"/link{i}") || n.Contains($"link{i}"))
                {
                    if (!armJointMap.ContainsKey(i))
                        armJointMap[i] = body;
                }
            }

            // 自己反発や不要な揺れを防ぐため、アーム各関節の初期パラメータを安定化
            if (n.Contains("link") || n.Contains("piper"))
            {
                body.useGravity = false;
                body.angularDamping = 10f;
                body.linearDamping = 10f;
                body.jointFriction = 5f;
            }
        }

        wheelCtrl.leftWheel = leftWheel;
        wheelCtrl.rightWheel = rightWheel;
        wheelPub.leftWheel = leftWheel;
        wheelPub.rightWheel = rightWheel;

        List<ArticulationBody> jointList = new List<ArticulationBody>();
        for (int i = 1; i <= 7; i++)
        {
            if (armJointMap.ContainsKey(i))
            {
                jointList.Add(armJointMap[i]);
            }
        }

        if (jointList.Count > 0)
        {
            armCtrl.joints = jointList.ToArray();
            armPub.joints = jointList.ToArray();
        }

        // ロボット内部の全コライダー同士の自己衝突を無効化（めり込み反発による勝手な動きを排除）
        var colliders = robotRoot.GetComponentsInChildren<Collider>();
        for (int i = 0; i < colliders.Length; i++)
        {
            for (int j = i + 1; j < colliders.Length; j++)
            {
                Physics.IgnoreCollision(colliders[i], colliders[j], true);
            }
        }

        // RealSense カメラのセットアップ
        Transform opticalFrame = null;
        Transform cameraLink = null;
        foreach (var t in robotRoot.GetComponentsInChildren<Transform>())
        {
            if (t.name.Contains("camera_color_optical_frame"))
            {
                opticalFrame = t;
            }
            else if (t.name.Contains("camera_link") && cameraLink == null)
            {
                cameraLink = t;
            }
        }

        Transform targetMount = opticalFrame ?? cameraLink;
        if (targetMount != null)
        {
            var existingPub = targetMount.GetComponent<RealSenseCameraPublisher>();
            if (existingPub != null) DestroyImmediate(existingPub);
            var existingCam = targetMount.GetComponent<Camera>();
            if (existingCam != null) DestroyImmediate(existingCam);

            Transform camHolder = targetMount.Find("RealSense_Camera_Sensor");
            if (camHolder == null)
            {
                GameObject camGo = new GameObject("RealSense_Camera_Sensor");
                camHolder = camGo.transform;
                camHolder.SetParent(targetMount, false);
            }

            camHolder.localPosition = Vector3.zero;
            camHolder.localRotation = Quaternion.Euler(-90f, -90f, 0f);

            var cam = camHolder.GetComponent<Camera>();
            if (cam == null) cam = camHolder.gameObject.AddComponent<Camera>();
            cam.fieldOfView = 69f;
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 10f;
            cam.targetDisplay = 1;

            var camPub = camHolder.GetComponent<RealSenseCameraPublisher>();
            if (camPub == null) camPub = camHolder.gameObject.AddComponent<RealSenseCameraPublisher>();
            camPub.colorImageTopic = "/camera/camera/color/image_raw";
            camPub.colorCameraInfoTopic = "/camera/camera/color/camera_info";
            camPub.colorFrameId = "camera_color_optical_frame";
            simManager.cameraPublisher = camPub;
        }

        simManager.wheelController = wheelCtrl;
        simManager.wheelPublisher = wheelPub;
        simManager.armController = armCtrl;
        simManager.armPublisher = armPub;

        EditorUtility.SetDirty(robotRoot);
        EditorSceneManager.MarkSceneDirty(robotRoot.scene);
    }
}
#endif
