import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/app_parameters.dart';
import 'transport_interface.dart';

class WebSocketTransport implements TransportInterface {
  bool _isDisconnecting = false;

  final _connectionController = StreamController<bool>.broadcast();
  final Map<String, TopicCallback> _callbacks = {};

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  bool _advertisedCmdVel = false;

  @override
  Stream<bool> get connectionStatus => _connectionController.stream;

  @override
  Future<void> connect({Object? target, String? host, int? port}) async {
    await disconnect();
    final resolvedHost = host ?? AppParameters.defaultWifiHost;
    final resolvedPort = port ?? AppParameters.defaultWifiPort;
    final channel = WebSocketChannel.connect(Uri.parse('ws://$resolvedHost:$resolvedPort'));
    await channel.ready;
    _channel = channel;
    _advertisedCmdVel = false;
    _subscription = channel.stream.listen(
      _handleMessage,
      onDone: _handleClosedConnection,
      onError: (_) => _handleClosedConnection(),
      cancelOnError: true,
    );
    _connectionController.add(true);
  }

  void _handleMessage(dynamic rawMessage) {
    final message = jsonDecode(rawMessage as String) as Map<String, dynamic>;
    if (message['op'] == 'publish') {
      final topic = message['topic'] as String?;
      final payload = message['msg'] as Map<String, dynamic>?;
      if (topic != null && payload != null) {
        _callbacks[topic]?.call(payload);
      }
    }
  }

  @override
  Future<void> sendTwist(double linearX, double angularZ) async {
    final channel = _channel;
    if (channel == null) {
      throw StateError('WebSocket is not connected');
    }

    if (!_advertisedCmdVel) {
      channel.sink.add(jsonEncode({
        'op': 'advertise',
        'topic': AppParameters.cmdVelTopic,
        'type': 'geometry_msgs/msg/Twist',
      }));
      _advertisedCmdVel = true;
    }

    channel.sink.add(jsonEncode({
      'op': 'publish',
      'topic': AppParameters.cmdVelTopic,
      'msg': {
        'linear': {'x': linearX, 'y': 0.0, 'z': 0.0},
        'angular': {'x': 0.0, 'y': 0.0, 'z': angularZ},
      },
    }));
  }

  @override
  Future<void> subscribe(String topic, String type, TopicCallback callback) async {
    _callbacks[topic] = callback;
    _channel?.sink.add(jsonEncode({'op': 'subscribe', 'topic': topic, 'type': type}));
  }

  @override
  Future<void> unsubscribe(String topic) async {
    _callbacks.remove(topic);
    _channel?.sink.add(jsonEncode({'op': 'unsubscribe', 'topic': topic}));
  }

  void _handleClosedConnection() {
    if (_isDisconnecting) {
      return;
    }
    _subscription = null;
    _channel = null;
    _advertisedCmdVel = false;
    _connectionController.add(false);
  }

  @override
  Future<void> disconnect() async {
    _isDisconnecting = true;
    try {
      await _subscription?.cancel();
      await _channel?.sink.close();
    } finally {
      _subscription = null;
      _channel = null;
      _advertisedCmdVel = false;
      _isDisconnecting = false;
      _connectionController.add(false);
    }
  }
}
