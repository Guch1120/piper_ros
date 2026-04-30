import 'dart:async';

import 'package:flutter/material.dart';

import '../config/app_parameters.dart';
import '../models/twist_command.dart';

class DpadWidget extends StatefulWidget {
  const DpadWidget({
    super.key,
    required this.enabled,
    required this.onCommand,
    required this.onStop,
  });

  final bool enabled;
  final Future<void> Function(TwistCommand command) onCommand;
  final Future<void> Function() onStop;

  @override
  State<DpadWidget> createState() => _DpadWidgetState();
}

class _DpadWidgetState extends State<DpadWidget> {
  Timer? _repeatTimer;

  @override
  void dispose() {
    _repeatTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const buttonSize = 44.0;
    const gap = 6.0;
    const side = (buttonSize * 3) + (gap * 2);

    return FittedBox(
      fit: BoxFit.contain,
      child: SizedBox(
        width: side,
        height: side,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _holdButton(
              Icons.keyboard_arrow_up,
              TwistCommand(linearX: AppParameters.dpadForwardLinear, angularZ: 0),
              buttonSize,
            ),
            const SizedBox(height: gap),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _holdButton(
                  Icons.keyboard_arrow_left,
                  TwistCommand(linearX: 0, angularZ: AppParameters.dpadTurnAngular),
                  buttonSize,
                ),
                const SizedBox(width: gap),
                SizedBox(
                  width: buttonSize,
                  height: buttonSize,
                  child: FilledButton(
                    onPressed: widget.enabled ? _stopRepeating : null,
                    style: FilledButton.styleFrom(
                      backgroundColor: const Color(0xFFE66043),
                      minimumSize: const Size(buttonSize, buttonSize),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(buttonSize / 3),
                      ),
                      padding: EdgeInsets.zero,
                    ),
                    child: const Icon(Icons.stop, color: Colors.white, size: 20),
                  ),
                ),
                const SizedBox(width: gap),
                _holdButton(
                  Icons.keyboard_arrow_right,
                  TwistCommand(linearX: 0, angularZ: -AppParameters.dpadTurnAngular),
                  buttonSize,
                ),
              ],
            ),
            const SizedBox(height: gap),
            _holdButton(
              Icons.keyboard_arrow_down,
              TwistCommand(linearX: AppParameters.dpadBackwardLinear, angularZ: 0),
              buttonSize,
            ),
          ],
        ),
      ),
    );
  }

  Widget _holdButton(IconData icon, TwistCommand command, double size) {
    return SizedBox(
      width: size,
      height: size,
      child: Listener(
        onPointerDown: widget.enabled ? (_) => _startRepeating(command) : null,
        onPointerUp: widget.enabled ? (_) => _stopRepeating() : null,
        onPointerCancel: widget.enabled ? (_) => _stopRepeating() : null,
        child: AbsorbPointer(
          child: FilledButton(
            onPressed: widget.enabled ? () {} : null,
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFF2A4D3E),
              minimumSize: Size(size, size),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(size / 3)),
              padding: EdgeInsets.zero,
            ),
            child: Icon(icon, color: Colors.white, size: size * 0.58),
          ),
        ),
      ),
    );
  }

  void _startRepeating(TwistCommand command) {
    _repeatTimer?.cancel();
    widget.onCommand(command);
    _repeatTimer = Timer.periodic(const Duration(milliseconds: 90), (_) {
      widget.onCommand(command);
    });
  }

  void _stopRepeating() {
    _repeatTimer?.cancel();
    _repeatTimer = null;
    widget.onStop();
  }
}
