import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'controllers/app_controller.dart';
import 'screens/main_screen.dart';

void main() {
  runApp(
    ChangeNotifierProvider(
      create: (_) => AppController(),
      child: const KobukiControllerApp(),
    ),
  );
}

class KobukiControllerApp extends StatelessWidget {
  const KobukiControllerApp({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();

    return MaterialApp(
      title: 'Kobuki Controller',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF0B8F6A),
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: const Color(0xFFF5F1E8),
        textTheme: Theme.of(context).textTheme.apply(
              bodyColor: const Color(0xFF1A221D),
              displayColor: const Color(0xFF1A221D),
            ),
        useMaterial3: true,
      ),
      home: MainScreen(controller: controller),
    );
  }
}
