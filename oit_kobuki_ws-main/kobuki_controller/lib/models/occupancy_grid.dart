class OccupancyGridModel {
  const OccupancyGridModel({
    required this.width,
    required this.height,
    required this.resolution,
    required this.originX,
    required this.originY,
    required this.data,
  });

  final int width;
  final int height;
  final double resolution;
  final double originX;
  final double originY;
  final List<int> data;

  factory OccupancyGridModel.fromRosbridge(Map<String, dynamic> message) {
    final info = message['info'] as Map<String, dynamic>? ?? const {};
    final origin = info['origin'] as Map<String, dynamic>? ?? const {};
    final position = origin['position'] as Map<String, dynamic>? ?? const {};
    final data = (message['data'] as List<dynamic>? ?? const [])
        .map((value) => (value as num).toInt())
        .toList();
    return OccupancyGridModel(
      width: (info['width'] as num?)?.toInt() ?? 0,
      height: (info['height'] as num?)?.toInt() ?? 0,
      resolution: (info['resolution'] as num?)?.toDouble() ?? 0.05,
      originX: (position['x'] as num?)?.toDouble() ?? 0.0,
      originY: (position['y'] as num?)?.toDouble() ?? 0.0,
      data: data,
    );
  }
}
