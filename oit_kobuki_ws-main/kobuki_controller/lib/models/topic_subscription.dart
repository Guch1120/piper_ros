class TopicSubscription {
  const TopicSubscription({
    required this.topic,
    required this.type,
    this.enabled = false,
    this.label,
  });

  final String topic;
  final String type;
  final bool enabled;
  final String? label;

  String get displayLabel => label ?? topic;
}
