import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import 'transport_interface.dart';

class BleDiscoveredDevice {
  const BleDiscoveredDevice({
    required this.device,
    required this.name,
    required this.rssi,
  });

  final BluetoothDevice device;
  final String name;
  final int rssi;
}

class BleTransport implements TransportInterface {
  static final Guid serviceUuid = Guid('12345678-1234-5678-1234-56789abcdef0');
  static final Guid commandUuid = Guid('12345678-1234-5678-1234-56789abcdef1');

  final _connectionController = StreamController<bool>.broadcast();

  BluetoothDevice? _device;
  BluetoothCharacteristic? _commandCharacteristic;
  StreamSubscription<BluetoothConnectionState>? _deviceStateSubscription;

  @override
  Stream<bool> get connectionStatus => _connectionController.stream;

  Future<List<BleDiscoveredDevice>> scanDevices({
    required String targetName,
    required Guid serviceUuid,
  }) async {
    await _ensureAdapterReady();

    final seen = <String, BleDiscoveredDevice>{};
    final subscription = FlutterBluePlus.scanResults.listen((results) {
      for (final result in results) {
        final advName = result.advertisementData.advName;
        final platformName = result.device.platformName;
        final name = advName.isNotEmpty ? advName : platformName;
        if (name == targetName) {
          seen[result.device.remoteId.str] = BleDiscoveredDevice(
            device: result.device,
            name: name,
            rssi: result.rssi,
          );
        }
      }
    });

    if (FlutterBluePlus.isScanningNow) {
      await FlutterBluePlus.stopScan();
    }

    await FlutterBluePlus.startScan(
      timeout: const Duration(seconds: 4),
      withServices: [serviceUuid],
      androidUsesFineLocation: false,
    );
    await FlutterBluePlus.isScanning.where((isScanning) => isScanning == false).first;
    await subscription.cancel();
    return seen.values.toList()..sort((a, b) => b.rssi.compareTo(a.rssi));
  }

  @override
  Future<void> connect({Object? target, String? host, int? port}) async {
    if (target is! BleDiscoveredDevice) {
      throw ArgumentError('BLE transport requires a BleDiscoveredDevice target');
    }
    await _ensureAdapterReady();
    _device = target.device;
    await _device!.connect(
      license: License.free,
      timeout: const Duration(seconds: 10),
    );
    await _deviceStateSubscription?.cancel();
    _deviceStateSubscription = _device!.connectionState.listen((state) {
      if (state == BluetoothConnectionState.disconnected) {
        _commandCharacteristic = null;
        _connectionController.add(false);
      }
    });
    final services = await _device!.discoverServices();
    for (final service in services) {
      if (service.uuid != serviceUuid) {
        continue;
      }
      for (final characteristic in service.characteristics) {
        if (characteristic.uuid == commandUuid) {
          _commandCharacteristic = characteristic;
          _connectionController.add(true);
          return;
        }
      }
    }
    throw StateError('BLE command characteristic not found');
  }

  @override
  Future<void> sendTwist(double linearX, double angularZ) async {
    final characteristic = _commandCharacteristic;
    if (characteristic == null) {
      throw StateError('BLE device is not connected');
    }
    final bytes = ByteData(8)
      ..setFloat32(0, linearX, Endian.little)
      ..setFloat32(4, angularZ, Endian.little);
    try {
      await characteristic.write(bytes.buffer.asUint8List(), withoutResponse: false);
    } catch (error) {
      _commandCharacteristic = null;
      _connectionController.add(false);
      throw StateError('BLE write failed: $error');
    }
  }

  @override
  Future<void> subscribe(String topic, String type, TopicCallback callback) async {}

  @override
  Future<void> unsubscribe(String topic) async {}

  @override
  Future<void> disconnect() async {
    await _deviceStateSubscription?.cancel();
    _deviceStateSubscription = null;
    if (_device != null) {
      try {
        await _device!.disconnect();
      } catch (_) {
        // Ignore disconnect failures.
      }
    }
    _device = null;
    _commandCharacteristic = null;
    _connectionController.add(false);
  }

  Future<void> _ensureAdapterReady() async {
    if (!await FlutterBluePlus.isSupported) {
      throw StateError('Bluetooth LE is not supported on this device');
    }

    var state = FlutterBluePlus.adapterStateNow;
    if (state == BluetoothAdapterState.unknown) {
      state = await FlutterBluePlus.adapterState.first;
    }

    if (state == BluetoothAdapterState.unauthorized) {
      throw StateError('Bluetooth permission is not granted');
    }

    if (state != BluetoothAdapterState.on && Platform.isAndroid) {
      await FlutterBluePlus.turnOn();
    }

    state = await FlutterBluePlus.adapterState.firstWhere(
      (value) => value != BluetoothAdapterState.unknown,
    );
    if (state == BluetoothAdapterState.unauthorized) {
      throw StateError('Bluetooth permission is not granted');
    }
    if (state != BluetoothAdapterState.on) {
      throw StateError('Bluetooth adapter is not enabled');
    }
  }
}
