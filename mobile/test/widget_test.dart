import "package:flutter/material.dart";
import "package:flutter_test/flutter_test.dart";
import "package:network_control_center/main.dart";

void main() {
  test("device form payload preserves registration fields", () {
    final data = DeviceFormData(
      kind: "esxi",
      name: " ESXi-01 ",
      host: "10.0.0.10",
      port: "443",
      username: "root",
      secret: "secret",
      caFile: "/ca.pem",
      fingerprint: "AA:BB",
      profile: "secure_gateway",
    );
    final payload = data.toPayload();
    expect(payload["name"], "ESXi-01");
    expect(payload["host"], "10.0.0.10");
    expect(payload["port"], 443);
    expect(payload["profile"], "secure_gateway");
    expect(payload["username"], "root");
  });

  testWidgets("Arabic text renders as a single widget", (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Text("\u0625\u0636\u0627\u0641\u0629 \u062C\u0647\u0627\u0632"))));
    expect(find.text("\u0625\u0636\u0627\u0641\u0629 \u062C\u0647\u0627\u0632"), findsOneWidget);
  });

  testWidgets("powered off VM shows Power On button", (tester) async {
    final vm = Vm(id: "vm1", name: "Very Long VM Name That Should Not Collapse", state: "off", guest: "Ubuntu", tools: "unknown");
    final device = Device(id: "d1", name: "ESXi-01", kind: "esxi", host: "10.0.0.1", port: 443, state: "online", detail: "", vms: [vm], profile: "p");
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: VmTile(vm: vm, device: device, onCommand: (_, __, ___) {}))));
    expect(find.text("Very Long VM Name That Should Not Collapse"), findsOneWidget);
    expect(find.text("\u062A\u0634\u063A\u064A\u0644"), findsOneWidget);
  });

  testWidgets("powered on VM shows restart and shutdown buttons", (tester) async {
    final vm = Vm(id: "vm2", name: "VM Two", state: "on", guest: "Windows", tools: "guestToolsRunning");
    final device = Device(id: "d1", name: "ESXi-01", kind: "esxi", host: "10.0.0.1", port: 443, state: "online", detail: "", vms: [vm], profile: "p");
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: VmTile(vm: vm, device: device, onCommand: (_, __, ___) {}))));
    expect(find.text("VM Two"), findsOneWidget);
    expect(find.text("\u0625\u0639\u0627\u062F\u0629 \u062A\u0634\u063A\u064A\u0644"), findsOneWidget);
    expect(find.text("\u0625\u064A\u0642\u0627\u0641 \u0622\u0645\u0646"), findsOneWidget);
  });
}
