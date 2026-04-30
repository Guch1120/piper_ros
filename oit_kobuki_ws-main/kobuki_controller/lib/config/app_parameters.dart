class AppParameters {
  // BLE advertisement name shown to the mobile app.
  static const bleDeviceName = String.fromEnvironment(
    'KOBUKI_BLE_DEVICE_NAME',
    defaultValue: 'KobukiController',
  );

  // ROS topic used for velocity commands from both BLE and Wi-Fi transports.
  static const cmdVelTopic = String.fromEnvironment(
    'KOBUKI_CMD_VEL_TOPIC',
    defaultValue: '/commands/velocity',
  );

  // Visualization topics subscribed from rosbridge in Wi-Fi mode.
  static const mapTopic = String.fromEnvironment(
    'KOBUKI_MAP_TOPIC',
    defaultValue: '/map',
  );
  static const scanTopic = String.fromEnvironment(
    'KOBUKI_SCAN_TOPIC',
    defaultValue: '/scan',
  );
  static const odomTopic = String.fromEnvironment(
    'KOBUKI_ODOM_TOPIC',
    defaultValue: '/odom',
  );
  static const tfTopic = String.fromEnvironment(
    'KOBUKI_TF_TOPIC',
    defaultValue: '/tf',
  );
  static const filteredScanTopic = String.fromEnvironment(
    'KOBUKI_FILTERED_SCAN_TOPIC',
    defaultValue: '/filtered_scan',
  );
  static const amclPoseTopic = String.fromEnvironment(
    'KOBUKI_AMCL_POSE_TOPIC',
    defaultValue: '/amcl_pose',
  );
  static const planTopic = String.fromEnvironment(
    'KOBUKI_PLAN_TOPIC',
    defaultValue: '/plan',
  );

  // Maximum joystick command scaling for forward/backward speed [m/s].
  static final maxLinearSpeed = double.parse(
    const String.fromEnvironment(
      'KOBUKI_MAX_LINEAR_SPEED',
      defaultValue: '0.15',
    ),
  );

  // Maximum joystick command scaling for turn rate [rad/s].
  static final maxAngularSpeed = double.parse(
    const String.fromEnvironment(
      'KOBUKI_MAX_ANGULAR_SPEED',
      defaultValue: '0.40',
    ),
  );

  // D-pad hold command for forward motion [m/s].
  static final dpadForwardLinear = double.parse(
    const String.fromEnvironment(
      'KOBUKI_DPAD_FORWARD_LINEAR',
      defaultValue: '0.15',
    ),
  );

  // D-pad hold command for backward motion [m/s].
  static final dpadBackwardLinear = double.parse(
    const String.fromEnvironment(
      'KOBUKI_DPAD_BACKWARD_LINEAR',
      defaultValue: '-0.15',
    ),
  );

  // D-pad hold command for left/right turn rate [rad/s].
  static final dpadTurnAngular = double.parse(
    const String.fromEnvironment(
      'KOBUKI_DPAD_TURN_ANGULAR',
      defaultValue: '0.40',
    ),
  );

  // Default rosbridge host shown in the Wi-Fi settings UI.
  static const defaultWifiHost = String.fromEnvironment(
    'KOBUKI_WIFI_HOST',
    defaultValue: '192.168.179.1',
  );

  // Default rosbridge port shown in the Wi-Fi settings UI.
  static const defaultWifiPort = int.fromEnvironment(
    'KOBUKI_WIFI_PORT',
    defaultValue: 9090,
  );
}
