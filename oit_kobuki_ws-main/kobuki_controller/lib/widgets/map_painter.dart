import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../config/app_parameters.dart';
import '../models/laser_scan.dart';
import '../models/occupancy_grid.dart';

class MapPainter extends CustomPainter {
  MapPainter({
    required this.enabledTopics,
    required this.latestMessages,
  });

  final Set<String> enabledTopics;
  final Map<String, Map<String, dynamic>> latestMessages;

  @override
  void paint(Canvas canvas, Size size) {
    final background = Paint()..color = const Color(0xFF18261E);
    canvas.drawRRect(
      RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(22)),
      background,
    );

    final gridPaint = Paint()
      ..color = const Color(0x1FFFFFFF)
      ..strokeWidth = 1;
    for (double x = 0; x < size.width; x += 28) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), gridPaint);
    }
    for (double y = 0; y < size.height; y += 28) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    final world = _WorldView.fromMessages(latestMessages, size);

    _paintMap(canvas, world);
    _paintPlan(canvas, world);
    _paintScan(canvas, world, AppParameters.scanTopic, const Color(0xFF7AE3A5));
    _paintScan(canvas, world, AppParameters.filteredScanTopic, const Color(0xFF42C8F5));
    _paintPath(canvas, world);
    _paintRobot(canvas, world);
    _paintLegend(canvas, size, world);
  }

  void _paintMap(Canvas canvas, _WorldView world) {
    final raw = latestMessages[AppParameters.mapTopic];
    if (!enabledTopics.contains(AppParameters.mapTopic) || raw == null) {
      return;
    }

    final grid = OccupancyGridModel.fromRosbridge(raw);
    if (grid.width == 0 || grid.height == 0 || grid.data.isEmpty) {
      return;
    }

    final freePaint = Paint()..color = const Color(0xFFDBE8D2);
    final occupiedPaint = Paint()..color = const Color(0xFF4B5F50);
    final unknownPaint = Paint()..color = const Color(0xFF223128);

    for (int y = 0; y < grid.height; y++) {
      for (int x = 0; x < grid.width; x++) {
        final index = y * grid.width + x;
        if (index >= grid.data.length) {
          continue;
        }
        final value = grid.data[index];
        final worldX = grid.originX + (x + 0.5) * grid.resolution;
        final worldY = grid.originY + (y + 0.5) * grid.resolution;
        final center = world.worldToCanvas(worldX, worldY);
        final rect = Rect.fromCenter(
          center: center,
          width: world.scale * grid.resolution,
          height: world.scale * grid.resolution,
        );
        if (value < 0) {
          canvas.drawRect(rect, unknownPaint);
        } else if (value >= 50) {
          canvas.drawRect(rect, occupiedPaint);
        } else if (value <= 15) {
          canvas.drawRect(rect, freePaint);
        }
      }
    }
  }

  void _paintScan(Canvas canvas, _WorldView world, String topic, Color color) {
    final raw = latestMessages[topic];
    if (!enabledTopics.contains(topic) || raw == null) {
      return;
    }

    final scan = LaserScanModel.fromRosbridge(raw);
    final robotPose = world.robotPose;
    if (scan.ranges.isEmpty || robotPose == null) {
      return;
    }

    final pointPaint = Paint()..color = color;
    for (int i = 0; i < scan.ranges.length; i++) {
      final range = scan.ranges[i];
      if (!range.isFinite || range < math.max(scan.rangeMin, 0.02) || range > scan.rangeMax) {
        continue;
      }
      final localAngle = scan.angleMin + scan.angleIncrement * i;
      final globalAngle = robotPose.yaw + localAngle;
      final x = robotPose.x + math.cos(globalAngle) * range;
      final y = robotPose.y + math.sin(globalAngle) * range;
      canvas.drawCircle(world.worldToCanvas(x, y), 2.2, pointPaint);
    }
  }

  void _paintPlan(Canvas canvas, _WorldView world) {
    final raw = latestMessages[AppParameters.planTopic];
    if (!enabledTopics.contains(AppParameters.planTopic) || raw == null) {
      return;
    }

    final poses = raw['poses'] as List<dynamic>? ?? const [];
    if (poses.length < 2) {
      return;
    }

    final path = Path();
    for (int i = 0; i < poses.length; i++) {
      final pose = poses[i] as Map<String, dynamic>? ?? const {};
      final poseValue = pose['pose'] as Map<String, dynamic>? ?? const {};
      final position = poseValue['position'] as Map<String, dynamic>? ?? const {};
      final x = (position['x'] as num?)?.toDouble() ?? 0.0;
      final y = (position['y'] as num?)?.toDouble() ?? 0.0;
      final point = world.worldToCanvas(x, y);
      if (i == 0) {
        path.moveTo(point.dx, point.dy);
      } else {
        path.lineTo(point.dx, point.dy);
      }
    }

    final planPaint = Paint()
      ..color = const Color(0xFFE66043)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;
    canvas.drawPath(path, planPaint);
  }

  void _paintPath(Canvas canvas, _WorldView world) {
    if (world.odomPath.length < 2) {
      return;
    }
    final path = Path()..moveTo(world.odomPath.first.dx, world.odomPath.first.dy);
    for (final point in world.odomPath.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }
    final odomPaint = Paint()
      ..color = const Color(0xFF88B3FF)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;
    canvas.drawPath(path, odomPaint);
  }

  void _paintRobot(Canvas canvas, _WorldView world) {
    final pose = world.robotPose;
    if (pose == null) {
      return;
    }
    final center = world.worldToCanvas(pose.x, pose.y);
    final heading = Offset(math.cos(pose.yaw), -math.sin(pose.yaw));
    final lateral = Offset(-heading.dy, heading.dx);
    final robotLength = math.max(world.scale * 0.18, 10.0).toDouble();
    final robotWidth = math.max(world.scale * 0.12, 7.0).toDouble();

    final nose = center + heading * robotLength;
    final rearLeft = center - heading * robotLength * 0.55 + lateral * robotWidth * 0.75;
    final rearRight = center - heading * robotLength * 0.55 - lateral * robotWidth * 0.75;

    final robotPath = Path()
      ..moveTo(nose.dx, nose.dy)
      ..lineTo(rearLeft.dx, rearLeft.dy)
      ..lineTo(rearRight.dx, rearRight.dy)
      ..close();

    final robotPaint = Paint()..color = const Color(0xFFF5B245);
    canvas.drawPath(robotPath, robotPaint);
    canvas.drawCircle(center, 3.5, Paint()..color = Colors.white);
  }

  void _paintLegend(Canvas canvas, Size size, _WorldView world) {
    final liveTopics = enabledTopics.where(latestMessages.containsKey).toList()..sort();
    final textPainter = TextPainter(
      text: TextSpan(
        text: liveTopics.isEmpty
            ? 'Preview mode\nConnect Wi-Fi and enable topics'
            : 'Live: ${liveTopics.join(', ')}',
        style: const TextStyle(color: Colors.white70, fontSize: 14, height: 1.4),
      ),
      textDirection: TextDirection.ltr,
    )..layout(maxWidth: size.width - 32);
    textPainter.paint(canvas, const Offset(16, 16));

    final robotPose = world.robotPose;
    if (robotPose == null) {
      return;
    }
    final poseText = TextPainter(
      text: TextSpan(
        text: 'Pose x=${robotPose.x.toStringAsFixed(2)} y=${robotPose.y.toStringAsFixed(2)} yaw=${(robotPose.yaw * 180 / math.pi).toStringAsFixed(0)}deg',
        style: const TextStyle(color: Colors.white54, fontSize: 12),
      ),
      textDirection: TextDirection.ltr,
    )..layout(maxWidth: size.width - 32);
    poseText.paint(canvas, Offset(16, size.height - 24));
  }

  @override
  bool shouldRepaint(covariant MapPainter oldDelegate) {
    return oldDelegate.enabledTopics != enabledTopics ||
        oldDelegate.latestMessages.toString() != latestMessages.toString();
  }
}

class _WorldView {
  _WorldView({
    required this.scale,
    required this.centerX,
    required this.centerY,
    required this.size,
    required this.robotPose,
    required this.odomPath,
  });

  final double scale;
  final double centerX;
  final double centerY;
  final Size size;
  final _Pose2D? robotPose;
  final List<Offset> odomPath;

  factory _WorldView.fromMessages(
    Map<String, Map<String, dynamic>> latestMessages,
    Size size,
  ) {
    final mapRaw = latestMessages[AppParameters.mapTopic];
    final odomRaw = latestMessages[AppParameters.odomTopic];
    final tfRaw = latestMessages[AppParameters.tfTopic];
    final odomHistoryRaw = latestMessages['__odom_history__'];

    OccupancyGridModel? map;
    if (mapRaw != null) {
      map = OccupancyGridModel.fromRosbridge(mapRaw);
    }

    final odomPose = odomRaw == null
        ? null
        : _Pose2D.fromPoseMessage(odomRaw['pose'] as Map<String, dynamic>? ?? const {});
    final tfPose = _Pose2D.fromTfMessage(tfRaw);
    final robotPose = tfPose ?? odomPose;

    final historyPoints = <Offset>[];
    final rawHistory = odomHistoryRaw?['points'] as List<dynamic>? ?? const [];
    for (final item in rawHistory) {
      final point = item as Map<String, dynamic>? ?? const {};
      historyPoints.add(Offset(
        (point['x'] as num?)?.toDouble() ?? 0.0,
        (point['y'] as num?)?.toDouble() ?? 0.0,
      ));
    }

    double worldWidth;
    double worldHeight;
    double centerX;
    double centerY;

    if (map != null && map.width > 0 && map.height > 0) {
      worldWidth = map.width * map.resolution;
      worldHeight = map.height * map.resolution;
      centerX = map.originX + worldWidth / 2;
      centerY = map.originY + worldHeight / 2;
    } else if (historyPoints.isNotEmpty) {
      var minX = historyPoints.first.dx;
      var maxX = historyPoints.first.dx;
      var minY = historyPoints.first.dy;
      var maxY = historyPoints.first.dy;
      for (final point in historyPoints.skip(1)) {
        minX = math.min(minX, point.dx);
        maxX = math.max(maxX, point.dx);
        minY = math.min(minY, point.dy);
        maxY = math.max(maxY, point.dy);
      }
      worldWidth = math.max(maxX - minX, 2.0) + 1.0;
      worldHeight = math.max(maxY - minY, 2.0) + 1.0;
      centerX = (minX + maxX) / 2;
      centerY = (minY + maxY) / 2;
    } else {
      worldWidth = 10.0;
      worldHeight = 10.0;
      centerX = robotPose?.x ?? 0.0;
      centerY = robotPose?.y ?? 0.0;
    }

    final scale = math.min(size.width / worldWidth, size.height / worldHeight) * 0.9;
    final odomPath = <Offset>[];

    if (historyPoints.isNotEmpty) {
      for (final point in historyPoints) {
        odomPath.add(_project(point.dx, point.dy, size, centerX, centerY, scale));
      }
    } else {
      final pathSource = latestMessages[AppParameters.planTopic];
      if (pathSource != null) {
        final poses = pathSource['poses'] as List<dynamic>? ?? const [];
        for (final pose in poses) {
          final poseMap = pose as Map<String, dynamic>? ?? const {};
          final poseValue = poseMap['pose'] as Map<String, dynamic>? ?? const {};
          final position = poseValue['position'] as Map<String, dynamic>? ?? const {};
          final x = (position['x'] as num?)?.toDouble() ?? 0.0;
          final y = (position['y'] as num?)?.toDouble() ?? 0.0;
          odomPath.add(_project(x, y, size, centerX, centerY, scale));
        }
      } else if (odomPose != null) {
        odomPath.add(_project(odomPose.x, odomPose.y, size, centerX, centerY, scale));
      }
    }

    return _WorldView(
      scale: scale.isFinite && scale > 0 ? scale : 32,
      centerX: centerX,
      centerY: centerY,
      size: size,
      robotPose: robotPose,
      odomPath: odomPath,
    );
  }

  Offset worldToCanvas(double x, double y) => _project(x, y, size, centerX, centerY, scale);

  static Offset _project(double x, double y, Size size, double centerX, double centerY, double scale) {
    final dx = (x - centerX) * scale + size.width / 2;
    final dy = size.height / 2 - (y - centerY) * scale;
    return Offset(dx, dy);
  }
}

class _Pose2D {
  const _Pose2D({required this.x, required this.y, required this.yaw});

  final double x;
  final double y;
  final double yaw;

  factory _Pose2D.fromPoseMessage(Map<String, dynamic> wrapper) {
    final pose = wrapper['pose'] as Map<String, dynamic>? ?? wrapper;
    final position = pose['position'] as Map<String, dynamic>? ?? const {};
    final orientation = pose['orientation'] as Map<String, dynamic>? ?? const {};
    return _Pose2D(
      x: (position['x'] as num?)?.toDouble() ?? 0.0,
      y: (position['y'] as num?)?.toDouble() ?? 0.0,
      yaw: _yawFromQuaternion(orientation),
    );
  }

  static _Pose2D? fromTfMessage(Map<String, dynamic>? message) {
    if (message == null) {
      return null;
    }
    final transforms = message['transforms'] as List<dynamic>? ?? const [];
    for (final item in transforms) {
      final transformStamped = item as Map<String, dynamic>? ?? const {};
      final child = transformStamped['child_frame_id'] as String? ?? '';
      if (child != 'base_footprint' && child != 'base_link') {
        continue;
      }
      final transform = transformStamped['transform'] as Map<String, dynamic>? ?? const {};
      final translation = transform['translation'] as Map<String, dynamic>? ?? const {};
      final rotation = transform['rotation'] as Map<String, dynamic>? ?? const {};
      return _Pose2D(
        x: (translation['x'] as num?)?.toDouble() ?? 0.0,
        y: (translation['y'] as num?)?.toDouble() ?? 0.0,
        yaw: _yawFromQuaternion(rotation),
      );
    }
    return null;
  }

  static double _yawFromQuaternion(Map<String, dynamic> q) {
    final x = (q['x'] as num?)?.toDouble() ?? 0.0;
    final y = (q['y'] as num?)?.toDouble() ?? 0.0;
    final z = (q['z'] as num?)?.toDouble() ?? 0.0;
    final w = (q['w'] as num?)?.toDouble() ?? 1.0;
    final siny = 2.0 * (w * z + x * y);
    final cosy = 1.0 - 2.0 * (y * y + z * z);
    return math.atan2(siny, cosy);
  }
}
