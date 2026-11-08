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
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Text("????? ????"))));
    expect(find.text("????? ????"), findsOneWidget);
  });
}

