import 'package:flutter/material.dart';

import '../models/topic_subscription.dart';

class TopicPanel extends StatelessWidget {
  const TopicPanel({
    super.key,
    required this.topics,
    required this.enabledTopics,
    required this.visible,
    required this.onToggle,
  });

  final List<TopicSubscription> topics;
  final Set<String> enabledTopics;
  final bool visible;
  final void Function(TopicSubscription topic) onToggle;

  @override
  Widget build(BuildContext context) {
    if (!visible) {
      return const SizedBox.shrink();
    }

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: topics
          .map(
            (topic) => FilterChip(
              label: Text(topic.displayLabel),
              selected: enabledTopics.contains(topic.topic),
              onSelected: (_) => onToggle(topic),
            ),
          )
          .toList(),
    );
  }
}
