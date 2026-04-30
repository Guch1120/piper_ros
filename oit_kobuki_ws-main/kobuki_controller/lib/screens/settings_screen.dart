import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../controllers/app_controller.dart';
import '../transport/ble_transport.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<AppController>(
      builder: (context, controller, _) {
        return Scaffold(
          appBar: AppBar(title: const Text('Connection Settings')),
          body: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              _ConnectionStatusCard(controller: controller),
              const SizedBox(height: 20),
              SegmentedButton<ConnectionMode>(
                segments: const [
                  ButtonSegment(value: ConnectionMode.ble, label: Text('BLE')),
                  ButtonSegment(value: ConnectionMode.wifi, label: Text('Wi-Fi')),
                ],
                selected: {controller.mode},
                onSelectionChanged: controller.isBusy
                    ? null
                    : (selection) => controller.setMode(selection.first),
              ),
              const SizedBox(height: 20),
              if (controller.mode == ConnectionMode.ble) _BleSettings(controller: controller),
              if (controller.mode == ConnectionMode.wifi) _WifiSettings(controller: controller),
            ],
          ),
        );
      },
    );
  }
}

class _ConnectionStatusCard extends StatelessWidget {
  const _ConnectionStatusCard({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final color = controller.isConnected
        ? const Color(0xFF1E8E5A)
        : controller.isBusy
            ? const Color(0xFFB78015)
            : const Color(0xFF8D3B2A);
    final label = controller.isConnected
        ? 'Connected'
        : controller.isBusy
            ? 'Connecting'
            : 'Offline';

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        children: [
          Container(
            width: 12,
            height: 12,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: Theme.of(context).textTheme.titleMedium),
                Text(controller.statusText, style: Theme.of(context).textTheme.bodyMedium),
              ],
            ),
          ),
          if (controller.isBusy)
            const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2.4),
            ),
        ],
      ),
    );
  }
}

class _BleSettings extends StatelessWidget {
  const _BleSettings({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        FilledButton.tonalIcon(
          onPressed: controller.isBusy ? null : controller.scanBleDevices,
          icon: const Icon(Icons.bluetooth_searching),
          label: Text(controller.isBusy ? 'Scanning...' : 'Scan BLE devices'),
        ),
        const SizedBox(height: 12),
        RadioGroup<BleDiscoveredDevice>(
          groupValue: controller.selectedBleDevice,
          onChanged: controller.isBusy ? (_) {} : controller.selectBleDevice,
          child: Column(
            children: [
              for (final device in controller.scannedDevices)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Radio<BleDiscoveredDevice>(value: device),
                  title: Text(device.name),
                  subtitle: Text('${device.device.remoteId.str}  RSSI ${device.rssi}'),
                  onTap: controller.isBusy ? null : () => controller.selectBleDevice(device),
                ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            FilledButton(
              onPressed: controller.isBusy ? null : controller.connect,
              child: Text(controller.isBusy ? 'Connecting BLE...' : 'Connect BLE'),
            ),
            if (controller.isConnected)
              OutlinedButton(
                onPressed: controller.isBusy ? null : controller.disconnect,
                child: const Text('Disconnect'),
              ),
          ],
        ),
      ],
    );
  }
}

class _WifiSettings extends StatelessWidget {
  const _WifiSettings({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        TextFormField(
          initialValue: controller.wifiHost,
          decoration: const InputDecoration(labelText: 'Host', border: OutlineInputBorder()),
          onChanged: controller.updateWifiHost,
          enabled: !controller.isBusy,
        ),
        const SizedBox(height: 12),
        TextFormField(
          initialValue: controller.wifiPort,
          decoration: const InputDecoration(labelText: 'Port', border: OutlineInputBorder()),
          keyboardType: TextInputType.number,
          onChanged: controller.updateWifiPort,
          enabled: !controller.isBusy,
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            FilledButton(
              onPressed: controller.isBusy ? null : controller.connect,
              child: Text(controller.isBusy ? 'Connecting Wi-Fi...' : 'Connect Wi-Fi'),
            ),
            if (controller.isConnected)
              OutlinedButton(
                onPressed: controller.isBusy ? null : controller.disconnect,
                child: const Text('Disconnect'),
              ),
          ],
        ),
      ],
    );
  }
}
