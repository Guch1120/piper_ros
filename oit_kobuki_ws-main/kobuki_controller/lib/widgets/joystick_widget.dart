import 'dart:math' as math;

import 'package:flutter/material.dart';

class JoystickWidget extends StatefulWidget {
  const JoystickWidget({
    super.key,
    required this.onChanged,
    required this.onReleased,
  });

  final void Function(double x, double y) onChanged;
  final Future<void> Function() onReleased;

  @override
  State<JoystickWidget> createState() => _JoystickWidgetState();
}

class _JoystickWidgetState extends State<JoystickWidget> {
  Offset _delta = Offset.zero;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = math.min(constraints.maxWidth, constraints.maxHeight);
        final radius = size / 2;
        final knobRadius = size * 0.18;

        return GestureDetector(
          onPanUpdate: (details) {
            final box = context.findRenderObject() as RenderBox?;
            final local = box?.globalToLocal(details.globalPosition) ?? Offset.zero;
            final centered = local - Offset(radius, radius);
            final distance = centered.distance;
            final limited = distance > radius - knobRadius
                ? centered / distance * (radius - knobRadius)
                : centered;
            setState(() => _delta = limited);
            widget.onChanged(
              (limited.dx / (radius - knobRadius)).clamp(-1.0, 1.0),
              (limited.dy / (radius - knobRadius)).clamp(-1.0, 1.0),
            );
          },
          onPanEnd: (_) => _reset(),
          onPanCancel: _reset,
          child: Center(
            child: SizedBox(
              width: size,
              height: size,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: const RadialGradient(
                    colors: [Color(0xFF2D4A3D), Color(0xFF15211B)],
                  ),
                  border: Border.all(color: const Color(0xFF6FB083), width: 1.5),
                ),
                child: Stack(
                  alignment: Alignment.center,
                  children: [
                    Container(width: size * 0.28, height: 1, color: const Color(0x556FB083)),
                    Container(width: 1, height: size * 0.28, color: const Color(0x556FB083)),
                    Transform.translate(
                      offset: _delta,
                      child: Container(
                        width: knobRadius * 2,
                        height: knobRadius * 2,
                        decoration: const BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: LinearGradient(
                            colors: [Color(0xFFF0C95C), Color(0xFFB78015)],
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  void _reset() {
    setState(() => _delta = Offset.zero);
    widget.onReleased();
  }
}
