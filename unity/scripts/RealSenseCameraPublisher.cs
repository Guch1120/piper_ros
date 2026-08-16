using System;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;
using RosMessageTypes.Std;
using RosMessageTypes.BuiltinInterfaces;

/// <summary>
/// RealSense D435i ハンドカメラの映像およびカメラ情報を ROS 2 へ配信する C# スクリプト (Unity 側)。
/// Piper アーム先端の camera_color_optical_frame / camera_link に配置した Camera コンポーネントから
/// カラー画像 (ImageMsg) およびカメラ内部パラメータ (CameraInfoMsg) を定期送信します。
/// </summary>
[RequireComponent(typeof(Camera))]
public class RealSenseCameraPublisher : MonoBehaviour
{
    [Header("ROS Topics")]
    [Tooltip("カラー画像トピック名 (実機 RealSense 完全互換)")]
    public string colorImageTopic = "/camera/camera/color/image_raw";
    [Tooltip("カラーカメラ情報トピック名")]
    public string colorCameraInfoTopic = "/camera/camera/color/camera_info";

    [Header("Frame Settings")]
    [Tooltip("カラー画像の TF frame_id (ROS 座標系: 右=X, 下=Y, 前=Z)")]
    public string colorFrameId = "camera_color_optical_frame";

    [Header("Resolution & Rate")]
    [Tooltip("画像幅 (px)")]
    public int imageWidth = 640;
    [Tooltip("画像高さ (px)")]
    public int imageHeight = 480;
    [Tooltip("配信周波数 (Hz)")]
    public float publishHz = 30f;

    [Header("Encoding")]
    [Tooltip("画像エンコーディング (rgb8 or bgr8)")]
    public string encoding = "rgb8";

    private Camera targetCamera;
    private RenderTexture renderTexture;
    private Texture2D texture2D;
    private ROSConnection ros;
    private byte[] imageBuffer;
    private float lastPublishTime = 0f;

    void Start()
    {
        targetCamera = GetComponent<Camera>();
        ros = ROSConnection.GetOrCreateInstance();

        // トピックの登録
        ros.RegisterPublisher<ImageMsg>(colorImageTopic);
        ros.RegisterPublisher<CameraInfoMsg>(colorCameraInfoTopic);

        // RenderTexture と Texture2D の初期化
        renderTexture = new RenderTexture(imageWidth, imageHeight, 24, RenderTextureFormat.ARGB32);
        renderTexture.Create();
        targetCamera.targetTexture = renderTexture;

        texture2D = new Texture2D(imageWidth, imageHeight, TextureFormat.RGB24, false);
        imageBuffer = new byte[imageWidth * imageHeight * 3];
    }

    void OnDestroy()
    {
        if (renderTexture != null)
        {
            if (targetCamera != null && targetCamera.targetTexture == renderTexture)
                targetCamera.targetTexture = null;
            renderTexture.Release();
            Destroy(renderTexture);
        }
        if (texture2D != null)
        {
            Destroy(texture2D);
        }
    }

    void Update()
    {
        if (Time.time - lastPublishTime >= (1.0f / publishHz))
        {
            PublishCameraData();
            lastPublishTime = Time.time;
        }
    }

    private void PublishCameraData()
    {
        if (targetCamera == null || renderTexture == null || texture2D == null) return;

        float timeNow = Time.realtimeSinceStartup;
        int sec = (int)timeNow;
        uint nanosec = (uint)((timeNow - sec) * 1e9);

        var header = new HeaderMsg
        {
            stamp = new TimeMsg { sec = sec, nanosec = nanosec },
            frame_id = colorFrameId
        };

        // 1. RenderTexture からピクセル読み出し
        RenderTexture prevActive = RenderTexture.active;
        RenderTexture.active = renderTexture;
        texture2D.ReadPixels(new Rect(0, 0, imageWidth, imageHeight), 0, 0, false);
        texture2D.Apply();
        RenderTexture.active = prevActive;

        byte[] rawBytes = texture2D.GetRawTextureData();

        // Unity の Texture2D は下から上 (Bottom-Up) なので、ROS (Top-Down) に合わせて Y 軸反転
        int rowSize = imageWidth * 3;
        for (int y = 0; y < imageHeight; y++)
        {
            int srcRow = (imageHeight - 1 - y) * rowSize;
            int dstRow = y * rowSize;

            if (encoding == "rgb8")
            {
                Array.Copy(rawBytes, srcRow, imageBuffer, dstRow, rowSize);
            }
            else if (encoding == "bgr8")
            {
                for (int x = 0; x < imageWidth; x++)
                {
                    int srcIdx = srcRow + x * 3;
                    int dstIdx = dstRow + x * 3;
                    imageBuffer[dstIdx + 0] = rawBytes[srcIdx + 2]; // B
                    imageBuffer[dstIdx + 1] = rawBytes[srcIdx + 1]; // G
                    imageBuffer[dstIdx + 2] = rawBytes[srcIdx + 0]; // R
                }
            }
        }

        // 2. ImageMsg の作成と配信
        var imgMsg = new ImageMsg
        {
            header = header,
            height = (uint)imageHeight,
            width = (uint)imageWidth,
            encoding = encoding,
            is_bigendian = 0,
            step = (uint)rowSize,
            data = imageBuffer
        };
        ros.Publish(colorImageTopic, imgMsg);

        // 3. CameraInfoMsg の作成と配信
        var infoMsg = GenerateCameraInfo(header);
        ros.Publish(colorCameraInfoTopic, infoMsg);
    }

    private CameraInfoMsg GenerateCameraInfo(HeaderMsg header)
    {
        // Unity Camera の垂直 FOV から焦点距離 fx, fy を計算
        float fovRad = targetCamera.fieldOfView * Mathf.Deg2Rad;
        float fy = (imageHeight / 2.0f) / Mathf.Tan(fovRad / 2.0f);
        float fx = fy; // アスペクト比が等方的と仮定
        float cx = imageWidth / 2.0f;
        float cy = imageHeight / 2.0f;

        // 内部パラメータ行列 K (3x3 row-major)
        double[] K = new double[9]
        {
            fx, 0,  cx,
            0,  fy, cy,
            0,  0,  1
        };

        // 投影行列 P (3x4 row-major)
        double[] P = new double[12]
        {
            fx, 0,  cx, 0,
            0,  fy, cy, 0,
            0,  0,  1,  0
        };

        // 回転行列 R (3x3 単位行列)
        double[] R = new double[9]
        {
            1, 0, 0,
            0, 1, 0,
            0, 0, 1
        };

        return new CameraInfoMsg
        {
            header = header,
            height = (uint)imageHeight,
            width = (uint)imageWidth,
            distortion_model = "plumb_bob",
            d = new double[] { 0, 0, 0, 0, 0 },
            k = K,
            r = R,
            p = P,
            binning_x = 0,
            binning_y = 0,
            roi = new RegionOfInterestMsg { x_offset = 0, y_offset = 0, height = 0, width = 0, do_rectify = false }
        };
    }
}
