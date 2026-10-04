using System;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;
using RosMessageTypes.Std;
using RosMessageTypes.BuiltinInterfaces;

/// <summary>
/// RealSense D435i ハンドカメラのカラー画像・深度画像・カメラ情報を ROS 2 へ配信する C# スクリプト (Unity 側)。
/// 実機 RealSense D435i 完全互換トピック:
///   - カラー画像: /camera/camera/color/image_raw (rgb8)
///   - カラー情報: /camera/camera/color/camera_info
///   - 深度画像:   /camera/camera/aligned_depth_to_color/image_raw (16UC1, 単位: mm)
///   - 深度情報:   /camera/camera/aligned_depth_to_color/camera_info
/// </summary>
[RequireComponent(typeof(Camera))]
public class RealSenseCameraPublisher : MonoBehaviour
{
    [Header("ROS Color Topics")]
    public string colorImageTopic = "/camera/camera/color/image_raw";
    public string colorCameraInfoTopic = "/camera/camera/color/camera_info";
    public string colorFrameId = "camera_color_optical_frame";

    [Header("ROS Depth Topics")]
    public bool publishDepth = true;
    public string depthImageTopic = "/camera/camera/aligned_depth_to_color/image_raw";
    public string depthCameraInfoTopic = "/camera/camera/aligned_depth_to_color/camera_info";
    public string depthFrameId = "camera_color_optical_frame";

    [Header("Resolution & Rate")]
    public int imageWidth = 640;
    public int imageHeight = 480;
    public float publishHz = 30f;

    [Header("Encoding")]
    public string colorEncoding = "rgb8";

    private Camera targetCamera;
    private RenderTexture colorRT;
    private RenderTexture depthRT;
    private Texture2D colorTex;
    private Texture2D depthTex;
    private Material depthMaterial;
    private ROSConnection ros;
    private byte[] colorBuffer;
    private byte[] depthBuffer;
    private float lastPublishTime = 0f;

    // Linear Depth 変換用シェーダー
    private const string DepthShaderCode = @"
Shader ""Hidden/LinearDepthConverter""
{
    Properties { _MainTex (""Texture"", 2D) = ""white"" {} }
    SubShader
    {
        Cull Off ZWrite Off ZTest Always
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include ""UnityCG.cginc""

            sampler2D _CameraDepthTexture;

            struct appdata { float4 vertex : POSITION; float2 uv : TEXCOORD0; };
            struct v2f { float2 uv : TEXCOORD0; float4 vertex : SV_POSITION; };

            v2f vert (appdata v)
            {
                v2f o;
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv;
                return o;
            }

            float4 frag (v2f i) : SV_Target
            {
                float d = SAMPLE_DEPTH_TEXTURE(_CameraDepthTexture, i.uv);
                float linearDist = LinearEyeDepth(d); // ワールド距離 (m)
                return float4(linearDist, linearDist, linearDist, 1.0);
            }
            ENDCG
        }
    }";

    void Start()
    {
        targetCamera = GetComponent<Camera>();
        targetCamera.depthTextureMode |= DepthTextureMode.Depth;
        ros = ROSConnection.GetOrCreateInstance();

        // トピック登録
        ros.RegisterPublisher<ImageMsg>(colorImageTopic);
        ros.RegisterPublisher<CameraInfoMsg>(colorCameraInfoTopic);
        if (publishDepth)
        {
            ros.RegisterPublisher<ImageMsg>(depthImageTopic);
            ros.RegisterPublisher<CameraInfoMsg>(depthCameraInfoTopic);
        }

        // RenderTexture の作成
        colorRT = new RenderTexture(imageWidth, imageHeight, 24, RenderTextureFormat.ARGB32);
        colorRT.Create();

        colorTex = new Texture2D(imageWidth, imageHeight, TextureFormat.RGB24, false);
        colorBuffer = new byte[imageWidth * imageHeight * 3];

        if (publishDepth)
        {
            depthRT = new RenderTexture(imageWidth, imageHeight, 0, RenderTextureFormat.RFloat);
            depthRT.Create();
            depthTex = new Texture2D(imageWidth, imageHeight, TextureFormat.RFloat, false);
            depthBuffer = new byte[imageWidth * imageHeight * 2]; // 16-bit uint (16UC1)

            // シェーダーマテリアルの生成
            Shader s = Shader.Find("Hidden/LinearDepthConverter");
            if (s == null)
            {
                // 動的作成が効かない環境用にフォールバック
                s = Shader.Find("Unlit/Texture");
            }
            depthMaterial = new Material(Shader.Find("Hidden/LinearDepthConverter") ?? Shader.Find("Unlit/Texture"));
        }
    }

    void OnDestroy()
    {
        if (colorRT != null) { colorRT.Release(); Destroy(colorRT); }
        if (depthRT != null) { depthRT.Release(); Destroy(depthRT); }
        if (colorTex != null) Destroy(colorTex);
        if (depthTex != null) Destroy(depthTex);
        if (depthMaterial != null) Destroy(depthMaterial);
    }

    void Update()
    {
        if (Time.time - lastPublishTime >= (1.0f / publishHz))
        {
            PublishSensorData();
            lastPublishTime = Time.time;
        }
    }

    private void PublishSensorData()
    {
        if (targetCamera == null || colorRT == null || colorTex == null) return;

        float timeNow = Time.realtimeSinceStartup;
        int sec = (int)timeNow;
        uint nanosec = (uint)((timeNow - sec) * 1e9);

        var header = new HeaderMsg
        {
            stamp = new TimeMsg { sec = sec, nanosec = nanosec },
            frame_id = colorFrameId
        };

        // --- 1. カラー画像の取得と配信 ---
        // Game ビューの Display 描画を阻害しないよう、一時的に targetTexture を割り当てて Render
        RenderTexture prevTarget = targetCamera.targetTexture;
        targetCamera.targetTexture = colorRT;
        targetCamera.Render();
        targetCamera.targetTexture = prevTarget; // 画面描画用に即時復元

        RenderTexture prevActive = RenderTexture.active;
        RenderTexture.active = colorRT;
        colorTex.ReadPixels(new Rect(0, 0, imageWidth, imageHeight), 0, 0, false);
        colorTex.Apply();
        RenderTexture.active = prevActive;

        byte[] rawColor = colorTex.GetRawTextureData();
        int rowSizeColor = imageWidth * 3;

        // ROS (Top-Down) に合わせて Y 軸反転
        for (int y = 0; y < imageHeight; y++)
        {
            int srcRow = (imageHeight - 1 - y) * rowSizeColor;
            int dstRow = y * rowSizeColor;

            if (colorEncoding == "rgb8")
            {
                Array.Copy(rawColor, srcRow, colorBuffer, dstRow, rowSizeColor);
            }
            else if (colorEncoding == "bgr8")
            {
                for (int x = 0; x < imageWidth; x++)
                {
                    int srcIdx = srcRow + x * 3;
                    int dstIdx = dstRow + x * 3;
                    colorBuffer[dstIdx + 0] = rawColor[srcIdx + 2];
                    colorBuffer[dstIdx + 1] = rawColor[srcIdx + 1];
                    colorBuffer[dstIdx + 2] = rawColor[srcIdx + 0];
                }
            }
        }

        var colorMsg = new ImageMsg
        {
            header = header,
            height = (uint)imageHeight,
            width = (uint)imageWidth,
            encoding = colorEncoding,
            is_bigendian = 0,
            step = (uint)rowSizeColor,
            data = colorBuffer
        };
        ros.Publish(colorImageTopic, colorMsg);

        var colorInfoMsg = GenerateCameraInfo(header);
        ros.Publish(colorCameraInfoTopic, colorInfoMsg);

        // --- 2. 深度画像の取得と配信 (16UC1 [mm]) ---
        if (publishDepth && depthRT != null && depthTex != null)
        {
            var depthHeader = new HeaderMsg
            {
                stamp = header.stamp,
                frame_id = depthFrameId
            };

            // Depth Texture から距離画像（RFloat: メートル単位）を取得
            RenderTexture.active = colorRT;
            Graphics.Blit(colorRT, depthRT, depthMaterial);
            RenderTexture.active = depthRT;
            depthTex.ReadPixels(new Rect(0, 0, imageWidth, imageHeight), 0, 0, false);
            depthTex.Apply();
            RenderTexture.active = prevActive;

            // 浮動小数点距離 (m) から 16bit 整数 (mm) へ変換
            Color[] pixels = depthTex.GetPixels();
            float nearClip = targetCamera.nearClipPlane;
            float farClip = targetCamera.farClipPlane;

            for (int y = 0; y < imageHeight; y++)
            {
                int srcY = imageHeight - 1 - y; // Y 反転
                for (int x = 0; x < imageWidth; x++)
                {
                    int pixelIdx = srcY * imageWidth + x;
                    float depthMeters = pixels[pixelIdx].r;

                    if (float.IsNaN(depthMeters) || float.IsInfinity(depthMeters) || depthMeters <= 0f || depthMeters > farClip)
                    {
                        depthMeters = 0f;
                    }

                    // 1mm 単位の ushort (0〜65535 mm)
                    ushort depthMm = (ushort)Mathf.Clamp(depthMeters * 1000.0f, 0f, 65535f);

                    int dstByteIdx = (y * imageWidth + x) * 2;
                    depthBuffer[dstByteIdx + 0] = (byte)(depthMm & 0xFF);
                    depthBuffer[dstByteIdx + 1] = (byte)((depthMm >> 8) & 0xFF);
                }
            }

            var depthMsg = new ImageMsg
            {
                header = depthHeader,
                height = (uint)imageHeight,
                width = (uint)imageWidth,
                encoding = "16UC1",
                is_bigendian = 0,
                step = (uint)(imageWidth * 2),
                data = depthBuffer
            };
            ros.Publish(depthImageTopic, depthMsg);

            var depthInfoMsg = GenerateCameraInfo(depthHeader);
            ros.Publish(depthCameraInfoTopic, depthInfoMsg);
        }
    }

    private CameraInfoMsg GenerateCameraInfo(HeaderMsg header)
    {
        float fovRad = targetCamera.fieldOfView * Mathf.Deg2Rad;
        float fy = (imageHeight / 2.0f) / Mathf.Tan(fovRad / 2.0f);
        float fx = fy;
        float cx = imageWidth / 2.0f;
        float cy = imageHeight / 2.0f;

        double[] K = new double[9] { fx, 0, cx, 0, fy, cy, 0, 0, 1 };
        double[] P = new double[12] { fx, 0, cx, 0, 0, fy, cy, 0, 0, 0, 1, 0 };
        double[] R = new double[9] { 1, 0, 0, 0, 1, 0, 0, 0, 1 };

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
