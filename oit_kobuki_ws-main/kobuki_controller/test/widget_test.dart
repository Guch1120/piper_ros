import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:kobuki_controller/controllers/app_controller.dart';
import 'package:kobuki_controller/main.dart';

void main() {
  testWidgets('app renders title', (WidgetTester tester) async {
    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => AppController(),
        child: const KobukiControllerApp(),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('Kobuki Controller'), findsWidgets);
  });
}
