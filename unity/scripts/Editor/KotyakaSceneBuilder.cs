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
        // 1. 新規シーンの作成
        var newScene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        // 2. 照明 (Directional Light) の作成
        GameObject lightGo = new GameObject("Directional Light");
        Light light = lightGo.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.0f;
        light.color = Color.white;
        lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);

        // 3. 環境床面 (Ground Plane) の作成
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

        // 4. ROS Connection の初期化
        GameObject rosGo = new GameObject("ROSConnection");
        rosGo.AddComponent<ROSConnection>();

        // 5. シーン確認用メインカメラ (Main Camera)
        GameObject mainCamGo = new GameObject("Main Camera");
        var mainCam = mainCamGo.AddComponent<Camera>();
        mainCam.tag = "MainCamera";
        mainCamGo.AddComponent<AudioListener>();
        mainCamGo.transform.position = new Vector3(1.5f, 1.2f, -1.8f);
        mainCamGo.transform.rotation = Quaternion.Euler(25f, -35f, 0f);

        // 6. シーン保存
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
            // Hierarchy から自動で mobile_manipulator を探す
            selected = GameObject.Find("mobile_manipulator");
            if (selected == null)
            {
                EditorUtility.DisplayDialog("エラー", "Hierarchy 上でインポートしたロボット (mobile_manipulator) を選択してください。", "OK");
                return;
            }
        }

        // シーン上の不要な空の Kotyaka_Robot があれば削除
        var emptyRoots = GameObject.FindObjectsByType<GameObject>(FindObjectsSortMode.None);
        foreach (var go in emptyRoots)
        {
            if (go != selected && go.name == "Kotyaka_Robot" && go.transform.childCount == 0)
            {
                DestroyImmediate(go);
            }
        }

        SetupRobotComponents(selected);
        EditorUtility.DisplayDialog("完了", $"『{selected.name}』に車輪制御・アーム制御・RealSenseカメラ・統合マネージャーを自動設定しました！", "OK");
    }

    private static void SetupRobotComponents(GameObject robotRoot)
    {
        var simManager = robotRoot.GetComponent<KotyakaSimManager>() ?? robotRoot.AddComponent<KotyakaSimManager>();
        var wheelCtrl = robotRoot.GetComponent<KobukiWheelController>() ?? robotRoot.AddComponent<KobukiWheelController>();
        var wheelPub = robotRoot.GetComponent<KobukiWheelStatePublisher>() ?? robotRoot.AddComponent<KobukiWheelStatePublisher>();
        var armCtrl = robotRoot.GetComponent<PiperJointController>() ?? robotRoot.AddComponent<PiperJointController>();
        var armPub = robotRoot.GetComponent<PiperJointStatePublisher>() ?? robotRoot.AddComponent<PiperJointStatePublisher>();

        var bodies = robotRoot.GetComponentsInChildren<ArticulationBody>();
        ArticulationBody leftWheel = null;
        ArticulationBody rightWheel = null;
        
        // アーム関節検索
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
        }

        wheelCtrl.leftWheel = leftWheel;
        wheelCtrl.rightWheel = rightWheel;
        wheelPub.leftWheel = leftWheel;
        wheelPub.rightWheel = rightWheel;

        // link1〜link7 をリスト化
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

        // RealSense カメラのセットアップ
        Transform cameraFrame = null;
        foreach (var t in robotRoot.GetComponentsInChildren<Transform>())
        {
            if (t.name.Contains("camera_color_optical_frame"))
            {
                cameraFrame = t;
                break;
            }
            else if (t.name.Contains("camera_link") && cameraFrame == null)
            {
                cameraFrame = t;
            }
        }

        if (cameraFrame != null)
        {
            var cam = cameraFrame.GetComponent<Camera>() ?? cameraFrame.gameObject.AddComponent<Camera>();
            cam.fieldOfView = 69f;
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 10f;

            var camPub = cameraFrame.GetComponent<RealSenseCameraPublisher>() ?? cameraFrame.gameObject.AddComponent<RealSenseCameraPublisher>();
            camPub.colorImageTopic = "/camera/camera/color/image_raw";
            camPub.colorCameraInfoTopic = "/camera/camera/color/camera_info";
            camPub.colorFrameId = cameraFrame.name.Contains("optical") ? cameraFrame.name : "camera_color_optical_frame";
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
