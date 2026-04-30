import 'dart:async';

import 'package:flutter/material.dart';

import '../config/app_parameters.dart';
import '../models/topic_subscription.dart';
import '../models/twist_command.dart';
import '../transport/ble_transport.dart';
import '../transport/transport_interface.dart';
import '../transport/websocket_transport.dart';

enum ConnectionMode { ble, wifi }

class AppController extends ChangeNotifier {
  AppController() {
    _transport = _createTransport(ConnectionMode.ble);
    _bindTransport();
  }

  static const odomHistoryTopic = '__odom_history__';
  static const int _maxOdomHistoryPoints = 400;

  final List<TopicSubscription> availableTopics = const [
    TopicSubscription(topic: AppParameters.mapTopic, type: 'nav_msgs/msg/OccupancyGrid', enabled: true),
    TopicSubscription(topic: AppParameters.scanTopic, type: 'sensor_msgs/msg/LaserScan', enabled: true),
    TopicSubscription(topic: AppParameters.odomTopic, type: 'nav_msgs/msg/Odometry'),
    TopicSubscription(topic: AppParameters.tfTopic, type: 'tf2_msgs/msg/TFMessage', label: '/base_footprint (/tf)'),
    TopicSubscription(topic: AppParameters.filteredScanTopic, type: 'sensor_msgs/msg/LaserScan'),
    TopicSubscription(topic: AppParameters.amclPoseTopic, type: 'geometry_msgs/msg/PoseWithCovarianceStamped'),
    TopicSubscription(topic: AppParameters.planTopic, type: 'nav_msgs/msg/Path'),
  ];

  late TransportInterface _transport;
  StreamSubscription<bool>? _connectionSubscription;
  TwistCommand? _pendingCommand;
  bool _sendLoopActive = false;

  ConnectionMode mode = ConnectionMode.ble;
  bool isConnected = false;
  bool emergencyStop = false;
  bool isBusy = false;
  String statusText = 'Disconnected';
  String wifiHost = AppParameters.defaultWifiHost;
  String wifiPort = AppParameters.defaultWifiPort.toString();
  List<BleDiscoveredDevice> scannedDevices = const [];
  BleDiscoveredDevice? selectedBleDevice;
  TwistCommand lastCommand = TwistCommand.zero;
  final Map<String, Map<String, dynamic>> latestMessages = {};
  final Set<String> enabledTopics = {AppParameters.mapTopic, AppParameters.scanTopic};

  TransportInterface get transport => _transport;
  bool get supportsSubscriptions => mode == ConnectionMode.wifi;

  TransportInterface _createTransport(ConnectionMode targetMode) {
    return targetMode == ConnectionMode.ble ? BleTransport() : WebSocketTransport();
  }

  void _clearLiveMessages() {
    latestMessages.removeWhere((key, _) =>
        key == odomHistoryTopic ||
        availableTopics.any((topic) => topic.topic == key));
  }

  Future<void> _resetTransport(ConnectionMode nextMode) async {
    _pendingCommand = null;
    try {
      await _transport.disconnect();
    } catch (_) {
      // Ignore teardown failures while rebuilding the transport.
    }
    await _connectionSubscription?.cancel();
    _connectionSubscription = null;
    _transport = _createTransport(nextMode);
    _bindTransport();
  }

  void _bindTransport() {
    _connectionSubscription?.cancel();
    _connectionSubscription = _transport.connectionStatus.listen((connected) {
      isConnected = connected;
      statusText = connected ? 'Connected' : 'Disconnected';
      if (!connected) {
        _pendingCommand = null;
        _sendLoopActive = false;
      }
      notifyListeners();
    });
  }

  Future<void> setMode(ConnectionMode nextMode) async {
    if (mode == nextMode) {
      return;
    }
    await disconnect();
    mode = nextMode;
    await _resetTransport(nextMode);
    statusText = 'Mode changed to ${nextMode.name.toUpperCase()}';
    notifyListeners();
  }

  Future<void> scanBleDevices() async {
    if (_transport is! BleTransport || isBusy) {
      return;
    }
    isBusy = true;
    statusText = 'Scanning BLE devices...';
    notifyListeners();

    final bleTransport = _transport as BleTransport;
    try {
      scannedDevices = await bleTransport.scanDevices(
        targetName: AppParameters.bleDeviceName,
        serviceUuid: BleTransport.serviceUuid,
      );
      if (scannedDevices.isNotEmpty) {
        selectedBleDevice = scannedDevices.first;
      }
      statusText = scannedDevices.isEmpty ? 'No BLE devices found' : 'BLE scan complete';
    } catch (error) {
      statusText = 'BLE scan failed: $error';
    } finally {
      isBusy = false;
      notifyListeners();
    }
  }

  Future<void> connect() async {
    if (isBusy) {
      return;
    }

    isBusy = true;
    statusText = mode == ConnectionMode.ble ? 'Connecting over BLE...' : 'Connecting over Wi-Fi...';
    notifyListeners();

    try {
      await _resetTransport(mode);
      _clearLiveMessages();
      if (mode == ConnectionMode.ble) {
        final device = selectedBleDevice;
        if (device == null) {
          throw StateError('Select a BLE device first');
        }
        await _transport.connect(target: device);
      } else {
        await _transport.connect(
          host: wifiHost,
          port: int.tryParse(wifiPort) ?? AppParameters.defaultWifiPort,
        );
        await _resubscribeTopics();
      }
      statusText = 'Connected';
    } catch (error) {
      statusText = 'Connection failed: $error';
    } finally {
      isBusy = false;
      notifyListeners();
    }
  }

  Future<void> disconnect() async {
    _pendingCommand = null;
    try {
      await _transport.sendTwist(0, 0);
    } catch (_) {
      // Ignore stop failures during disconnect.
    }
    await _transport.disconnect();
    isConnected = false;
    _sendLoopActive = false;
    _clearLiveMessages();
    statusText = 'Disconnected';
    notifyListeners();
  }

  Future<void> sendCommand(TwistCommand command) async {
    if (!isConnected || emergencyStop) {
      return;
    }
    lastCommand = command;
    _pendingCommand = command;
    notifyListeners();
    await _flushPendingCommand();
  }

  Future<void> stopNow() async {
    lastCommand = TwistCommand.zero;
    _pendingCommand = TwistCommand.zero;
    notifyListeners();
    await _flushPendingCommand();
  }

  Future<void> _flushPendingCommand() async {
    if (_sendLoopActive) {
      return;
    }
    _sendLoopActive = true;
    try {
      while (_pendingCommand != null && isConnected) {
        final next = _pendingCommand!;
        _pendingCommand = null;
        await _transport.sendTwist(next.linearX, next.angularZ);
      }
    } catch (error) {
      _pendingCommand = null;
      await _transport.disconnect();
      isConnected = false;
      _sendLoopActive = false;
      statusText = 'Disconnected: $error';
      notifyListeners();
    } finally {
      _sendLoopActive = false;
    }
  }

  Future<void> setEmergencyStop(bool value) async {
    emergencyStop = value;
    if (value) {
      await stopNow();
      statusText = 'Emergency stop enabled';
    } else {
      statusText = 'Emergency stop released';
    }
    notifyListeners();
  }

  Future<void> toggleTopic(TopicSubscription topic) async {
    if (!supportsSubscriptions) {
      return;
    }

    if (enabledTopics.contains(topic.topic)) {
      enabledTopics.remove(topic.topic);
      await _transport.unsubscribe(topic.topic);
      latestMessages.remove(topic.topic);
      if (topic.topic == AppParameters.odomTopic) {
        latestMessages.remove(odomHistoryTopic);
      }
    } else {
      enabledTopics.add(topic.topic);
      await _transport.subscribe(topic.topic, topic.type, (message) {
        _handleTopicMessage(topic, message);
      });
    }
    notifyListeners();
  }

  Future<void> _resubscribeTopics() async {
    for (final topic in availableTopics.where((topic) => enabledTopics.contains(topic.topic))) {
      await _transport.subscribe(topic.topic, topic.type, (message) {
        _handleTopicMessage(topic, message);
      });
    }
  }

  void _handleTopicMessage(TopicSubscription topic, Map<String, dynamic> message) {
    latestMessages[topic.topic] = message;
    if (topic.topic == AppParameters.odomTopic) {
      _appendOdomHistory(message);
    }
    notifyListeners();
  }

  void _appendOdomHistory(Map<String, dynamic> message) {
    final poseWrapper = message['pose'] as Map<String, dynamic>? ?? const {};
    final pose = poseWrapper['pose'] as Map<String, dynamic>? ?? const {};
    final position = pose['position'] as Map<String, dynamic>? ?? const {};
    final x = (position['x'] as num?)?.toDouble();
    final y = (position['y'] as num?)?.toDouble();
    if (x == null || y == null) {
      return;
    }

    final existing = List<Map<String, dynamic>>.from(
      (latestMessages[odomHistoryTopic]?['points'] as List<dynamic>? ?? const []).map(
        (item) => Map<String, dynamic>.from(item as Map),
      ),
    );

    if (existing.isNotEmpty) {
      final last = existing.last;
      final dx = x - ((last['x'] as num?)?.toDouble() ?? x);
      final dy = y - ((last['y'] as num?)?.toDouble() ?? y);
      if (dx * dx + dy * dy < 0.0001) {
        return;
      }
    }

    existing.add({'x': x, 'y': y});
    if (existing.length > _maxOdomHistoryPoints) {
      existing.removeRange(0, existing.length - _maxOdomHistoryPoints);
    }
    latestMessages[odomHistoryTopic] = {'points': existing};
  }

  void selectBleDevice(BleDiscoveredDevice? device) {
    selectedBleDevice = device;
    notifyListeners();
  }

  void updateWifiHost(String value) {
    wifiHost = value;
    notifyListeners();
  }

  void updateWifiPort(String value) {
    wifiPort = value;
    notifyListeners();
  }

  @override
  Future<void> dispose() async {
    await _connectionSubscription?.cancel();
    await _transport.disconnect();
    super.dispose();
  }
}
