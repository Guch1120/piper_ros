typedef TopicCallback = void Function(Map<String, dynamic> message);

abstract class TransportInterface {
  Future<void> connect({Object? target, String? host, int? port});
  Future<void> sendTwist(double linearX, double angularZ);
  Future<void> subscribe(String topic, String type, TopicCallback callback);
  Future<void> unsubscribe(String topic);
  Future<void> disconnect();
  Stream<bool> get connectionStatus;
}
