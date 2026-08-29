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

        var groundCol = plane.GetComponent<Collider>();
        if (groundCol != null)
        {
            var groundPhysMat = new PhysicsMaterial("GroundMat")
            {
                staticFriction = 0.8f,
                dynamicFriction = 0.6f,
                bounciness = 0.0f,
                frictionCombine = PhysicsMaterialCombine.Average,
                bounceCombine = PhysicsMaterialCombine.Minimum
            };
            groundCol.material = groundPhysMat;
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

        Debug.Log($"[KotyakaSceneBuilder] Scene created at: {scenePath}");
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
                Debug.LogWarning("[KotyakaSceneBuilder] mobile_manipulator not found.");
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
        Debug.Log($"[KotyakaSceneBuilder] '{selected.name}' setup completed successfully with real mass & selective self-collisions!");
    }

    private static void SetupRobotComponents(GameObject robotRoot)
    {
        // 1. ルートおよび各リンクの初期姿勢と接地高さの適正化
        robotRoot.transform.position = new Vector3(0f, 0.015f, 0f);
        robotRoot.transform.rotation = Quaternion.identity;

        var baseLink = robotRoot.transform.Find("base_footprint/base_link");
        if (baseLink != null)
        {
            baseLink.localPosition = new Vector3(0f, 0.0102f, 0f);
            baseLink.localRotation = Quaternion.identity;
        }

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

            // 1. 実機カタログ通りの質量・重心 (Kobuki base_link: 2.4kg)
            if (n == "base_link" || n.EndsWith("/base_link"))
            {
                body.mass = 2.4f;
                body.centerOfMass = new Vector3(0.001f, 0.010f, 0f);
                body.angularDamping = 10f;
                body.linearDamping = 5f;
            }
            // 2. カチャカシェルフ (実機質量: 8.8kg)
            else if (n.Contains("shelf_link"))
            {
                body.mass = 8.8f;
                body.centerOfMass = new Vector3(0f, 0.3585f, 0f);
            }
            // 3. カメラ仮想フレーム・ダミーリンクの質量を極小化 & 重力無効化 (13kg過負荷の完全排除)
            else if (n.Contains("camera") || n.Contains("frame") || n.Contains("optical") || n == "gripper_base" || n == "tcp_link")
            {
                body.mass = (n == "camera_link") ? 0.072f : 0.0001f; // D435i 実測 72g
                body.useGravity = false;
                body.angularDamping = 10f;
                body.linearDamping = 10f;
            }
            // 4. アーム各関節のパラメータ適正化
            else if (n.Contains("link") || n.Contains("piper"))
            {
                body.useGravity = false;
                body.angularDamping = 10f;
                body.linearDamping = 10f;
                body.jointFriction = 5f;
            }

            if (body.dofCount > 0)
            {
                body.jointVelocity = new ArticulationReducedSpace(0f);
                body.jointForce = new ArticulationReducedSpace(0f);
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

        // 2. 選択的自己衝突 (Adjacent Pair / 親子関係のリンクのみ無効化し、非隣接リンク間の自己干渉は有効化)
        foreach (var body in bodies)
        {
            if (body.transform.parent != null)
            {
                var parentBody = body.transform.parent.GetComponentInParent<ArticulationBody>();
                if (parentBody != null)
                {
                    var childCols = body.GetComponentsInChildren<Collider>();
                    var parentCols = parentBody.GetComponentsInChildren<Collider>();
                    foreach (var c1 in childCols)
                    {
                        foreach (var c2 in parentCols)
                        {
                            Physics.IgnoreCollision(c1, c2, true);
                        }
                    }
                }
            }
        }

        // フィジックスマテリアルの適用 (キャスター引っかかり防止 & 主輪グリップ)
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

        var colliders = robotRoot.GetComponentsInChildren<Collider>();
        foreach (var col in colliders)
        {
            string n = col.gameObject.name.ToLower();
            string parentName = col.transform.parent != null ? col.transform.parent.name.ToLower() : "";

            if (n.Contains("wheel_left") || n.Contains("wheel_right") || parentName.Contains("wheel"))
            {
                col.material = wheelGripMat;
            }
            else if (n.Contains("caster") || n.Contains("shelf") || parentName.Contains("caster") || parentName.Contains("shelf"))
            {
                col.material = frictionlessMat;
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
