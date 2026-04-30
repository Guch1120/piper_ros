class LaserScanModel {
  const LaserScanModel({
    required this.angleMin,
    required this.angleIncrement,
    required this.rangeMin,
    required this.rangeMax,
    required this.ranges,
  });

  final double angleMin;
  final double angleIncrement;
  final double rangeMin;
  final double rangeMax;
  final List<double> ranges;

  factory LaserScanModel.fromRosbridge(Map<String, dynamic> message) {
    final ranges = (message['ranges'] as List<dynamic>? ?? const [])
        .map((value) => (value as num).toDouble())
        .toList();
    return LaserScanModel(
      angleMin: (message['angle_min'] as num?)?.toDouble() ?? 0,
      angleIncrement: (message['angle_increment'] as num?)?.toDouble() ?? 0,
      rangeMin: (message['range_min'] as num?)?.toDouble() ?? 0,
      rangeMax: (message['range_max'] as num?)?.toDouble() ?? 0,
      ranges: ranges,
    );
  }
}
