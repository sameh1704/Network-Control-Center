import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:network_control_center/main.dart';

Device _host() => Device(
  id: 'h1',
  name: 'ESXi-01',
  kind: 'esxi',
  host: '172.16.1.230',
  port: 443,
  state: 'online',
  detail: '',
  vms: [],
  profile: 'secure_gateway',
);

Vm _vm({required String state, String name = 'Ubuntu-01', String tools = 'guestToolsRunning'}) =>
    Vm(id: 'vm-1', name: name, state: state, guest: 'Ubuntu', tools: tools);

Future<void> pumpCard(
  WidgetTester tester, {
  required Vm vm,
  bool busy = false,
  Future<void> Function(Device, Vm, String)? onCommand,
}) async {
  await tester.pumpWidget(Directionality(
    textDirection: TextDirection.rtl,
    child: MaterialApp(
      home: Scaffold(
        body: vmCard(_host(), vm, busy: busy, onCommand: onCommand ?? (_, __, ___) async {}),
      ),
    ),
  ));
}

void main() {
  testWidgets('powered off VM shows Powered Off with enabled power-on button', (WidgetTester tester) async {
    String? requestedAction;
    await pumpCard(
      tester,
      vm: _vm(state: 'off'),
      onCommand: (_, __, action) async {
        requestedAction = action;
      },
    );
    expect(find.text('Powered Off'), findsOneWidget);
    expect(find.text('Ubuntu-01'), findsOneWidget);
    expect(find.text('تشغيل'), findsOneWidget);
    final btn = tester.widget<FilledButton>(find.byType(FilledButton).first);
    expect(btn.onPressed, isNotNull);
    await tester.tap(find.text('تشغيل'));
    expect(requestedAction, 'power_on');
    expect(find.text('إعادة تشغيل'), findsNothing);
    expect(find.text('إيقاف آمن'), findsNothing);
  });

  testWidgets('powered on VM shows Powered On with restart/shutdown buttons', (WidgetTester tester) async {
    await pumpCard(tester, vm: _vm(state: 'on'));
    expect(find.text('Powered On'), findsOneWidget);
    expect(find.text('إعادة تشغيل'), findsOneWidget);
    expect(find.text('إيقاف آمن'), findsOneWidget);
    expect(find.text('تشغيل'), findsNothing);
    expect(tester.widget<OutlinedButton>(find.byType(OutlinedButton).first).onPressed, isNotNull);
  });

  testWidgets('powered on VM without tools disables restart and shutdown', (WidgetTester tester) async {
    await pumpCard(tester, vm: _vm(state: 'on', tools: 'guestToolsNotRunning'));
    expect(find.text('إعادة تشغيل'), findsNothing);
    expect(find.text('إيقاف آمن'), findsNothing);
  });

  testWidgets('suspended VM shows Suspended with no enabled power action', (WidgetTester tester) async {
    await pumpCard(tester, vm: _vm(state: 'suspended'));
    expect(find.text('Suspended'), findsOneWidget);
    expect(find.text('تشغيل'), findsNothing);
    expect(find.text('إعادة تشغيل'), findsNothing);
    expect(find.text('إيقاف آمن'), findsNothing);
  });

  testWidgets('busy VM shows loading indicator and disables actions', (WidgetTester tester) async {
    await pumpCard(tester, vm: _vm(state: 'off'), busy: true);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('جاري التنفيذ...'), findsOneWidget);
    expect(find.text('تشغيل'), findsNothing);
  });

  testWidgets('VM name is constrained with ellipsis', (WidgetTester tester) async {
    const longName = 'AVeryLongVirtualMachineNameThatExceedsTwoLinesOnNarrowScreensAndShouldBeEllipsized';
    await pumpCard(tester, vm: _vm(state: 'off', name: longName));
    final titles = tester.widgetList<Text>(find.byType(Text));
    expect(titles.any((t) => t.maxLines == 2 && t.overflow == TextOverflow.ellipsis), isTrue);
  });

  testWidgets('VM card renders in RTL directionality', (WidgetTester tester) async {
    await pumpCard(tester, vm: _vm(state: 'off'));
    final title = tester.element(find.text('Ubuntu-01'));
    expect(Directionality.of(title), TextDirection.rtl);
    expect(find.text('Powered Off'), findsOneWidget);
  });
}
