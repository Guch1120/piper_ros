import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/app_parameters.dart';
import '../controllers/app_controller.dart';
import '../models/twist_command.dart';
import '../widgets/dpad_widget.dart';
import '../widgets/joystick_widget.dart';
import '../widgets/map_painter.dart';
import '../widgets/topic_panel.dart';
import 'settings_screen.dart';

class MainScreen extends StatelessWidget {
  const MainScreen({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider.value(
      value: controller,
      child: Consumer<AppController>(
        builder: (context, app, _) {
          final isWide = MediaQuery.of(context).size.width > 900;

          return Scaffold(
            appBar: AppBar(
              title: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Kobuki Controller'),
                  Text(app.statusText, style: Theme.of(context).textTheme.labelMedium),
                ],
              ),
              actions: [
                Padding(
                  padding: const EdgeInsets.only(right: 16),
                  child: Center(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: app.isConnected ? const Color(0xFF1E8E5A) : const Color(0xFF8D3B2A),
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        child: Text(
                          app.isConnected ? 'ONLINE' : 'OFFLINE',
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                        ),
                      ),
                    ),
                  ),
                ),
                IconButton(
                  onPressed: () async {
                    await Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const SettingsScreen()),
                    );
                  },
                  icon: const Icon(Icons.tune),
                ),
              ],
            ),
            body: Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  colors: [Color(0xFFF5F1E8), Color(0xFFE1EADC)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
              child: SafeArea(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: isWide
                      ? Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(flex: 7, child: _VisualizationPane(controller: app)),
                            const SizedBox(width: 20),
                            Expanded(flex: 5, child: _ControlPane(controller: app)),
                          ],
                        )
                      : Column(
                          children: [
                            Expanded(flex: 6, child: _VisualizationPane(controller: app)),
                            const SizedBox(height: 16),
                            Expanded(flex: 5, child: _ControlPane(controller: app)),
                          ],
                        ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _VisualizationPane extends StatelessWidget {
  const _VisualizationPane({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      color: Colors.white.withValues(alpha: 0.78),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Visualization', style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 12),
            Expanded(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(22),
                  gradient: const LinearGradient(
                    colors: [Color(0xFF122018), Color(0xFF1D3027)],
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                  ),
                ),
                child: CustomPaint(
                  painter: MapPainter(
                    enabledTopics: controller.enabledTopics,
                    latestMessages: controller.latestMessages,
                  ),
                  child: const SizedBox.expand(),
                ),
              ),
            ),
            const SizedBox(height: 12),
            TopicPanel(
              topics: controller.availableTopics,
              enabledTopics: controller.enabledTopics,
              visible: controller.supportsSubscriptions,
              onToggle: (topic) => controller.toggleTopic(topic),
            ),
          ],
        ),
      ),
    );
  }
}

class _ControlPane extends StatelessWidget {
  const _ControlPane({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      color: const Color(0xFF1B2721),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Drive',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(color: Colors.white),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: Row(
                children: [
                  Expanded(
                    flex: 6,
                    child: JoystickWidget(
                      onChanged: (x, y) {
                        final linear = (-y * AppParameters.maxLinearSpeed)
                            .clamp(-AppParameters.maxLinearSpeed, AppParameters.maxLinearSpeed);
                        final angularBase = x * AppParameters.maxAngularSpeed;
                        final angular = (linear >= 0 ? -angularBase : angularBase)
                            .clamp(-AppParameters.maxAngularSpeed, AppParameters.maxAngularSpeed);
                        final command = TwistCommand(
                          linearX: linear,
                          angularZ: angular,
                        );
                        controller.sendCommand(command);
                      },
                      onReleased: controller.stopNow,
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    flex: 5,
                    child: DpadWidget(
                      enabled: controller.isConnected && !controller.emergencyStop,
                      onCommand: controller.sendCommand,
                      onStop: controller.stopNow,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                FilterChip(
                  label: const Text('Emergency Stop'),
                  selected: controller.emergencyStop,
                  onSelected: controller.setEmergencyStop,
                  selectedColor: const Color(0xFFE66043),
                  labelStyle: const TextStyle(color: Colors.white),
                  checkmarkColor: Colors.white,
                ),
                _MetricChip(label: 'linear.x', value: controller.lastCommand.linearX.toStringAsFixed(2)),
                _MetricChip(label: 'angular.z', value: controller.lastCommand.angularZ.toStringAsFixed(2)),
                _MetricChip(label: 'mode', value: controller.mode.name.toUpperCase()),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MetricChip extends StatelessWidget {
  const _MetricChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF24322B),
        borderRadius: BorderRadius.circular(18),
      ),
      child: RichText(
        text: TextSpan(
          style: Theme.of(context).textTheme.labelLarge?.copyWith(color: Colors.white),
          children: [
            TextSpan(text: '$label  ', style: const TextStyle(color: Color(0xFFA7C3AE))),
            TextSpan(text: value, style: const TextStyle(fontWeight: FontWeight.w700)),
          ],
        ),
      ),
    );
  }
}
