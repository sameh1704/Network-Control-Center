import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';

void main() => runApp(const NccApp());

class NccApp extends StatelessWidget {
  const NccApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'مركز التحكم بالشبكة',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true, brightness: Brightness.dark),
        builder: (context, child) => Directionality(textDirection: TextDirection.rtl, child: child!),
        home: const DashboardScreen(),
      );
}

class Vm {
  final String id, name, state, guest, tools;
  Vm({required this.id, required this.name, required this.state, required this.guest, required this.tools});
  factory Vm.fromJson(Map<String, dynamic> j) => Vm(
        id: (j['id'] ?? '').toString(),
        name: (j['name'] ?? '').toString(),
        state: (j['state'] ?? 'unknown').toString(),
        guest: (j['guest'] ?? '').toString(),
        tools: (j['tools'] ?? 'unknown').toString(),
      );
}

class Device {
  final String id, name, kind, host, state, detail, profile;
  final int port;
  final List<Vm> vms;
  final bool pending;
  Device({required this.id, required this.name, required this.kind, required this.host, required this.port, required this.state, required this.detail, required this.vms, required this.profile, this.pending = false});
  factory Device.fromJson(Map<String, dynamic> j) => Device(
        id: (j['id'] ?? '').toString(),
        name: (j['name'] ?? '').toString(),
        kind: (j['kind'] ?? '').toString(),
        host: (j['host'] ?? '').toString(),
        port: (j['port'] is int) ? j['port'] as int : int.tryParse('${j['port']}') ?? 0,
        state: (j['state'] ?? 'unknown').toString(),
        detail: (j['detail'] ?? '').toString(),
        vms: ((j['vms'] as List?) ?? []).map((x) => Vm.fromJson(Map<String, dynamic>.from(x as Map))).toList(),
        profile: (j['profile'] ?? 'secure_gateway').toString(),
        pending: j['pending'] == true,
      );
  Device copyWith({String? state, String? detail, List<Vm>? vms}) => Device(
        id: id, name: name, kind: kind, host: host, port: port, state: state ?? this.state, detail: detail ?? this.detail, vms: vms ?? this.vms, profile: profile, pending: pending);
}

class ApiClient {
  String baseUrl;
  String token;
  ApiClient(this.baseUrl, this.token);
  Uri _uri(String path) => Uri.parse('${baseUrl.replaceAll(RegExp(r'/$'), '')}$path');
  Map<String, String> _headers() => {'X-API-Key': token, 'Content-Type': 'application/json'};
  Future<http.Response> get(String path) => http.get(_uri(path), headers: _headers()).timeout(const Duration(seconds: 20));
  Future<http.Response> post(String path, [Object? payload]) => http
      .post(_uri(path), headers: _headers(), body: payload == null ? null : jsonEncode(payload))
      .timeout(const Duration(seconds: 20));
  Future<http.Response> put(String path, Object? payload) => http
      .put(_uri(path), headers: _headers(), body: jsonEncode(payload))
      .timeout(const Duration(seconds: 20));
  Future<http.Response> delete(String path) => http.delete(_uri(path), headers: _headers()).timeout(const Duration(seconds: 20));
}

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final storage = const FlutterSecureStorage();
  final auth = LocalAuthentication();
  String url = '';
  String token = '';
  String error = '';
  List<Device> devices = [];
  List<Map<String, dynamic>> pending = [];
  bool busy = false;
  Timer? timer;
  bool appLock = false;
  bool unlocked = true;
  bool showWizard = false;

  @override
  void initState() {
    super.initState();
    _load();
    timer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (mounted && unlocked) refresh();
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    url = (await storage.read(key: 'gateway_url')) ?? (await storage.read(key: 'url')) ?? '';
    token = (await storage.read(key: 'gateway_key')) ?? (await storage.read(key: 'key')) ?? '';
    appLock = (await storage.read(key: 'app_lock')) == 'true';
    final p = await storage.read(key: 'pending_devices');
    if (p != null && p.isNotEmpty) {
      try { pending = (jsonDecode(p) as List).map((x) => Map<String, dynamic>.from(x as Map)).toList(); } catch (_) { pending = []; }
    }
    if (appLock) {
      unlocked = false;
      await _authenticate();
    }
    showWizard = url.isEmpty;
    if (mounted) setState(() {});
    await refresh();
  }

  Future<void> _authenticate() async {
    try {
      final ok = await auth.authenticate(localizedReason: 'فتح مركز التحكم بالشبكة');
      if (mounted) setState(() => unlocked = ok);
    } catch (_) {
      if (mounted) setState(() => unlocked = true);
    }
  }

  ApiClient? get client => (url.isEmpty || token.isEmpty) ? null : ApiClient(url, token);

  Future<void> _savePending() async {
    await storage.write(key: 'pending_devices', value: jsonEncode(pending));
  }

  Future<void> refresh() async {
    final c = client;
    if (busy || !unlocked) return;
    if (c == null) {
      // offline mode: show pending devices
      if (mounted) setState(() { devices = pending.map((x) => Device.fromJson({...x, 'pending': true, 'state': 'pending', 'detail': 'في انتظار الاتصال بالخادم'})).toList(); error = ''; });
      return;
    }
    setState(() => busy = true);
    try {
      final r = await c.get('/devices');
      if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}: ${r.body}');
      final list = (jsonDecode(r.body)['devices'] as List? ?? []);
      final synced = list.map((x) => Device.fromJson(Map<String, dynamic>.from(x as Map))).toList();
      // append pending not yet synced
      final pendingDevices = pending.map((x) => Device.fromJson({...x, 'pending': true, 'state': 'pending', 'detail': 'في انتظار المزامنة'})).toList();
      if (mounted) setState(() { devices = [...synced, ...pendingDevices]; error = ''; });
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<bool> confirm(String title, String msg) async {
    final r = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: Text(msg),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('تأكيد')),
        ],
      ),
    );
    return r ?? false;
  }

  Future<void> openGateway() async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => GatewayScreen(
      url: url, token: token,
      onSave: (u, t) async {
        url = u; token = t;
        await storage.write(key: 'gateway_url', value: url);
        await storage.write(key: 'gateway_key', value: token);
        await storage.write(key: 'url', value: url);
        await storage.write(key: 'key', value: token);
        if (mounted) { setState(() { showWizard = url.isEmpty; }); }
        await syncPending();
        await refresh();
      },
    )));
  }

  Future<void> openSettings() async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => SettingsScreen(
      url: url, token: token,
      onSave: (u, t) async {
        url = u; token = t;
        await storage.write(key: 'gateway_url', value: url);
        await storage.write(key: 'gateway_key', value: token);
        await storage.write(key: 'url', value: url);
        await storage.write(key: 'key', value: token);
        if (mounted) setState(() {});
        await refresh();
      },
      appLock: appLock,
      onAppLockChanged: (v) async {
        appLock = v;
        await storage.write(key: 'app_lock', value: v ? 'true' : 'false');
        if (mounted) setState(() {});
      },
      onOpenGateway: openGateway,
      onSyncPending: syncPending,
    )));
  }

  Future<void> syncPending() async {
    final c = client;
    if (c == null || pending.isEmpty) { toast('لا توجد أجهزة معلقة أو خادم غير مهيأ'); return; }
    int ok = 0;
    final remaining = <Map<String, dynamic>>[];
    for (final d in pending) {
      try {
        final payload = Map<String, dynamic>.from(d)..remove('pending');
        final r = await c.post('/devices', payload);
        if (r.statusCode < 400) { ok++; } else { remaining.add(d); }
      } catch (_) { remaining.add(d); }
    }
    pending = remaining;
    await _savePending();
    toast('تمت مزامنة $ok جهاز');
    await refresh();
  }

  Future<void> openHistory() async {
    final c = client;
    if (c == null) { toast('اضبط بوابة الإدارة أولاً'); return; }
    await Navigator.push(context, MaterialPageRoute(builder: (_) => HistoryScreen(client: c)));
  }

  Future<void> addDevice() async {
    final c = client;
    final edited = await showDialog<DeviceFormData>(
      context: context,
      builder: (ctx) => DeviceFormDialog(initial: null),
    );
    if (edited == null) return;
    final payload = edited.toPayload();
    if (c != null) {
      try {
        final r = await c.post('/devices', payload);
        if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}: ${r.body}');
        toast('تم حفظ الجهاز');
        await refresh();
      } catch (e) {
        toast('$e');
      }
    } else {
      // offline registration: store non-secret metadata only
      final meta = {
        'name': payload['name'],
        'kind': payload['kind'],
        'host': payload['host'],
        'port': payload['port'],
        'profile': payload['profile'],
        'ca_file': payload['ca_file'],
        'cert_fingerprint': payload['cert_fingerprint'],
        'username': payload['username'],
      };
      pending.add(meta);
      await _savePending();
      toast('تم حفظ الجهاز محليًا. سيتم مزامنته عند الاتصال بالخادم.');
      await refresh();
    }
  }

  Future<void> editDevice(Device d) async {
    final c = client;
    if (c == null || d.pending) { toast('التعديل متاح للأجهزة المزامنة فقط'); return; }
    final edited = await showDialog<DeviceFormData>(
      context: context,
      builder: (ctx) => DeviceFormDialog(initial: d),
    );
    if (edited == null) return;
    try {
      final r = await c.put('/devices/${d.id}', edited.toPayload(keepSecret: edited.secret.isEmpty));
      if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}: ${r.body}');
      toast('تم تحديث الجهاز');
      await refresh();
    } catch (e) {
      toast('$e');
    }
  }

  Future<void> deleteDevice(Device d) async {
    final c = client;
    if (d.pending) {
      pending.removeWhere((x) => x['name'] == d.name && x['host'] == d.host);
      await _savePending();
      toast('تم حذف الجهاز المعلق');
      await refresh();
      return;
    }
    if (c == null) return;
    if (!await confirm('حذف جهاز', 'هل تريد حذف ${d.name}؟')) return;
    try {
      final r = await c.delete('/devices/${d.id}');
      if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}: ${r.body}');
      toast('تم حذف الجهاز');
      await refresh();
    } catch (e) {
      toast('$e');
    }
  }

  Future<void> testDevice(Device d) async {
    final c = client;
    if (c == null || d.pending) { toast('اختبار الاتصال متاح بعد المزامنة'); return; }
    try {
      final r = await c.post('/devices/${d.id}/test');
      if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}: ${r.body}');
      final j = jsonDecode(r.body);
      toast('${j['state']}: ${j['detail']}');
      await refresh();
    } catch (e) {
      toast('$e');
    }
  }

  Future<void> showDiagnostics(Device d) async {
    final c = client;
    if (c == null || d.pending) { toast('التشخيص متاح بعد المزامنة'); return; }
    try {
      final r = await c.get('/devices/${d.id}/diagnostics');
      if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}: ${r.body}');
      final j = jsonDecode(r.body);
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text('تشخيص: ${d.name}'),
          content: Text('الحالة: ${j['state']}\n${j['detail']}\nوقت الفحص: ${j['checked_at']}'),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('إغلاق'))],
        ),
      );
    } catch (e) {
      toast('$e');
    }
  }

  Future<void> vmCommand(Device host, Vm vm, String action) async {
    final c = client;
    if (c == null) return;
    final label = action == 'power_on' ? 'تشغيل' : action == 'reboot_guest' ? 'إعادة تشغيل آمنة' : 'إيقاف آمن';
    if (!await confirm('تأكيد أمر', 'هل تريد $label ${vm.name} على ${host.name}؟')) return;
    try {
      final r = await c.post('/devices/${host.id}/vms/${Uri.encodeComponent(vm.id)}/command', {'action': action, 'confirm': true});
      if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}: ${r.body}');
      final j = jsonDecode(r.body);
      toast(j['message']?.toString() ?? 'تم إرسال الأمر');
      await refresh();
    } catch (e) {
      toast('$e');
    }
  }

  Color statusColor(String s) {
    if (s == 'on' || s == 'online' || s == 'healthy') return Colors.greenAccent;
    if (s == 'off') return Colors.redAccent;
    if (s == 'reachable' || s == 'pending') return Colors.amberAccent;
    return Colors.amberAccent;
  }

  Widget statusDot(String s) => Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.circle, color: statusColor(s), size: 10),
        const SizedBox(width: 6),
        Text(s),
      ]);

  Widget deviceCard(Device d) {
    final vms = d.vms;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: ExpansionTile(
        initiallyExpanded: d.kind == 'esxi',
        leading: Icon(d.kind == 'esxi' ? Icons.dns : d.kind == 'fortigate' ? Icons.shield : Icons.computer),
        title: Text(d.name),
        subtitle: Text('${d.host}:${d.port} · ${d.profile}'),
        trailing: statusDot(d.state),
        children: [
          if (d.detail.isNotEmpty) Padding(padding: const EdgeInsets.all(8), child: Text(d.detail, style: const TextStyle(fontSize: 11, color: Colors.grey))),
          if (d.pending) const Padding(padding: EdgeInsets.all(8), child: Text('جهاز معلق: سيتم مزامنته عند توفر بوابة الإدارة', style: TextStyle(color: Colors.amber))),
          ...vms.map((vm) => ListTile(
                leading: Icon(Icons.computer, color: vm.state == 'on' ? Colors.greenAccent : vm.state == 'off' ? Colors.redAccent : Colors.amberAccent),
                title: Text(vm.name),
                subtitle: Text('${vm.guest} · ${vm.state} · Tools: ${vm.tools}'),
                trailing: Wrap(spacing: 6, children: [
                  if (vm.state == 'off')
                    FilledButton.icon(onPressed: () => vmCommand(d, vm, 'power_on'), icon: const Icon(Icons.power_settings_new), label: const Text('تشغيل')),
                  if (vm.state == 'on') ...[
                    OutlinedButton.icon(
                      onPressed: vm.tools == 'guestToolsRunning' ? () => vmCommand(d, vm, 'reboot_guest') : null,
                      icon: const Icon(Icons.restart_alt),
                      label: const Text('إعادة تشغيل'),
                    ),
                    OutlinedButton.icon(
                      onPressed: vm.tools == 'guestToolsRunning' ? () => vmCommand(d, vm, 'shutdown_guest') : null,
                      icon: const Icon(Icons.power_off),
                      label: const Text('إيقاف آمن'),
                    ),
                    if (vm.tools != 'guestToolsRunning')
                      const Padding(padding: EdgeInsets.only(top: 4), child: Text('VMware Tools غير متاح: إعادة التشغيل/الإيقاف الآمن معطل', style: TextStyle(fontSize: 11, color: Colors.amber))),
                  ],
                ]),
              )),
          if (d.kind == 'esxi' && vms.isEmpty && !d.pending)
            const ListTile(title: Text('لا توجد VMs — تحقق من الاتصال وشهادة CA')),
          if (d.kind == 'fortigate')
            const ListTile(title: Text('إعادة تشغيل FortiGate معطلة حتى التحقق من الإصدار والصلاحيات')),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            child: Wrap(spacing: 8, children: [
              TextButton.icon(onPressed: () => testDevice(d), icon: const Icon(Icons.wifi_tethering), label: const Text('اختبار اتصال')),
              TextButton.icon(onPressed: () => showDiagnostics(d), icon: const Icon(Icons.troubleshoot), label: const Text('تشخيص')),
              TextButton.icon(onPressed: () => editDevice(d), icon: const Icon(Icons.edit), label: const Text('تعديل')),
              TextButton.icon(onPressed: () => deleteDevice(d), icon: const Icon(Icons.delete), label: const Text('حذف')),
            ]),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (!unlocked) {
      return Scaffold(
        body: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('التطبيق مقفل'),
            const SizedBox(height: 12),
            FilledButton(onPressed: _authenticate, child: const Text('فتح')),
          ]),
        ),
      );
    }
    if (showWizard) {
      return Scaffold(
        appBar: AppBar(title: const Text('إعداد أولي')),
        body: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('اختر طريقة البدء', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            FilledButton.icon(onPressed: () { setState(() => showWizard = false); openGateway(); }, icon: const Icon(Icons.vpn_lock), label: const Text('أ. إعداد بوابة الإدارة الآمنة')),
            const SizedBox(height: 8),
            OutlinedButton.icon(onPressed: () { setState(() => showWizard = false); }, icon: const Icon(Icons.devices), label: const Text('ب. إضافة أجهزة للاتصال لاحقًا')),
            const SizedBox(height: 12),
            const Text('يمكن تسجيل الأجهزة دون اتصال. سيتم مزامنتها عند توفر بوابة الإدارة.'),
          ]),
        ),
      );
    }
    return Scaffold(
      appBar: AppBar(
        title: const Text('مركز التحكم بالشبكة'),
        actions: [
          IconButton(tooltip: 'تحديث', onPressed: refresh, icon: const Icon(Icons.refresh)),
          IconButton(tooltip: 'مزامنة', onPressed: syncPending, icon: const Icon(Icons.sync)),
          IconButton(tooltip: 'السجل', onPressed: openHistory, icon: const Icon(Icons.history)),
          IconButton(tooltip: 'الإعدادات', onPressed: openSettings, icon: const Icon(Icons.settings)),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(onPressed: addDevice, icon: const Icon(Icons.add), label: const Text('إضافة جهاز')),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            if (busy) const LinearProgressIndicator(),
            if (url.isEmpty) const ListTile(title: Text('وضع عدم الاتصال: يمكن إضافة أجهزة ومزامنتها لاحقًا')),
            if (error.isNotEmpty) ListTile(leading: const Icon(Icons.warning_amber, color: Colors.amber), title: Text(error)),
            if (devices.isEmpty) const Padding(padding: EdgeInsets.all(12), child: Text('لا توجد أجهزة. اضغط إضافة جهاز.')),
            ...devices.map(deviceCard),
            const SizedBox(height: 80),
          ],
        ),
      ),
    );
  }
}

class DeviceFormData {
  String kind, name, host, port, username, secret, caFile, fingerprint, profile;
  DeviceFormData({required this.kind, required this.name, required this.host, required this.port, required this.username, required this.secret, required this.caFile, required this.fingerprint, required this.profile});
  Map<String, dynamic> toPayload({bool keepSecret = false}) => {
        'name': name.trim(),
        'kind': kind,
        'host': host.trim(),
        'port': int.tryParse(port) ?? 443,
        'username': username,
        'password': keepSecret ? '' : secret,
        'api_token': kind == 'fortigate' && !keepSecret ? secret : '',
        'ca_file': caFile.trim(),
        'cert_fingerprint': fingerprint.trim(),
        'profile': profile,
      };
}

class DeviceFormDialog extends StatefulWidget {
  final Device? initial;
  const DeviceFormDialog({super.key, required this.initial});
  @override
  State<DeviceFormDialog> createState() => _DeviceFormDialogState();
}

class _DeviceFormDialogState extends State<DeviceFormDialog> {
  late String kind;
  late String profile;
  final n = TextEditingController();
  final h = TextEditingController();
  final p = TextEditingController(text: '443');
  final u = TextEditingController();
  final s = TextEditingController();
  final ca = TextEditingController();
  final fp = TextEditingController();

  @override
  void initState() {
    super.initState();
    final d = widget.initial;
    kind = d?.kind ?? 'esxi';
    profile = d?.profile ?? 'secure_gateway';
    if (d != null) {
      n.text = d.name;
      h.text = d.host;
      p.text = '${d.port}';
    }
  }

  @override
  void dispose() {
    n.dispose(); h.dispose(); p.dispose(); u.dispose(); s.dispose(); ca.dispose(); fp.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.initial == null ? 'إضافة جهاز' : 'تعديل جهاز'),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButtonFormField<String>(
              initialValue: kind,
              items: const [
                DropdownMenuItem(value: 'esxi', child: Text('VMware ESXi')),
                DropdownMenuItem(value: 'fortigate', child: Text('FortiGate')),
                DropdownMenuItem(value: 'ubuntu', child: Text('Ubuntu Linux')),
              ],
              onChanged: (x) => setState(() => kind = x!),
              decoration: const InputDecoration(labelText: 'نوع الجهاز'),
            ),
            TextField(controller: n, decoration: const InputDecoration(labelText: 'اسم الجهاز')),
            TextField(controller: h, decoration: const InputDecoration(labelText: 'IP أو اسم مضيف (IPv4/IPv6/hostname)')),
            TextField(controller: p, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'منفذ الإدارة (1-65535)')),
            DropdownButtonFormField<String>(
              initialValue: profile,
              items: const [
                DropdownMenuItem(value: 'secure_gateway', child: Text('Secure Gateway (موصى به)')),
                DropdownMenuItem(value: 'private_vpn', child: Text('Private Network / VPN')),
                DropdownMenuItem(value: 'legacy_external', child: Text('Legacy External (ترحيل فقط)')),
              ],
              onChanged: (x) => setState(() => profile = x!),
              decoration: const InputDecoration(labelText: 'ملف الاتصال'),
            ),
            if (profile == 'legacy_external') const Text('تحذير: الاتصال الإداري المباشر من الإنترنت غير مفعل. هذا خيار ترحيل فقط.', style: TextStyle(color: Colors.amber, fontSize: 11)),
            if (kind == 'esxi') ...[
              TextField(controller: u, decoration: const InputDecoration(labelText: 'اسم مستخدم ESXi')),
              TextField(controller: s, obscureText: true, decoration: const InputDecoration(labelText: 'كلمة مرور ESXi (لا تُخزن محليًا)')),
              TextField(controller: ca, decoration: const InputDecoration(labelText: 'مسار ملف CA على الخادم')),
              TextField(controller: fp, decoration: const InputDecoration(labelText: 'بصمة الشهادة (اختياري)')),
            ],
            if (kind == 'fortigate') ...[
              TextField(controller: s, obscureText: true, decoration: const InputDecoration(labelText: 'API Token لـ FortiGate (لا يُخزن محليًا)')),
              TextField(controller: ca, decoration: const InputDecoration(labelText: 'مسار ملف CA (اختياري)')),
            ],
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('إلغاء')),
        FilledButton(
          onPressed: () {
            final port = int.tryParse(p.text) ?? 0;
            if (n.text.trim().isEmpty || h.text.trim().isEmpty || port < 1 || port > 65535) return;
            Navigator.pop(context, DeviceFormData(kind: kind, name: n.text, host: h.text, port: p.text, username: u.text, secret: s.text, caFile: ca.text, fingerprint: fp.text, profile: profile));
          },
          child: const Text('حفظ'),
        ),
      ],
    );
  }
}

class GatewayScreen extends StatefulWidget {
  final String url;
  final String token;
  final Future<void> Function(String, String) onSave;
  const GatewayScreen({super.key, required this.url, required this.token, required this.onSave});
  @override
  State<GatewayScreen> createState() => _GatewayScreenState();
}

class _GatewayScreenState extends State<GatewayScreen> {
  late final TextEditingController urlC;
  late final TextEditingController keyC;
  String status = '';
  bool testing = false;
  @override
  void initState() {
    super.initState();
    urlC = TextEditingController(text: widget.url);
    keyC = TextEditingController(text: widget.token);
  }
  @override
  void dispose() { urlC.dispose(); keyC.dispose(); super.dispose(); }

  Future<void> testConn() async {
    setState(() { testing = true; status = ''; });
    try {
      final uri = Uri.parse(urlC.text.trim());
      if (uri.scheme != 'https') throw Exception('HTTPS مطلوب');
      final c = ApiClient(urlC.text.trim(), keyC.text.trim());
      final r = await c.get('/health');
      if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}');
      final j = jsonDecode(r.body);
      setState(() => status = 'متصل: ${j['version']}');
    } catch (e) {
      setState(() => status = 'فشل: $e');
    } finally {
      setState(() => testing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('بوابة الإدارة الآمنة')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          TextField(controller: urlC, decoration: const InputDecoration(labelText: 'Gateway URL (HTTPS)', hintText: 'https://gateway.example.com:8443')),
          TextField(controller: keyC, obscureText: true, decoration: const InputDecoration(labelText: 'API Key / Session Token')),
          const SizedBox(height: 8),
          Row(children: [
            OutlinedButton(onPressed: testing ? null : testConn, child: Text(testing ? '...' : 'اختبار اتصال')),
            const SizedBox(width: 8),
            FilledButton(onPressed: () async {
              final u = urlC.text.trim();
              if (!u.startsWith('https://')) { setState(() => status = 'HTTPS مطلوب'); return; }
              await widget.onSave(u, keyC.text.trim());
              if (mounted) setState(() => status = 'تم الحفظ');
            }, child: const Text('حفظ')),
          ]),
          if (status.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(status)),
          const Divider(),
          const Text('متطلبات الأمان: TLS متحقق، مصادقة قوية، صلاحيات least-privilege، عدم كشف المنافذ الإدارية.'),
        ],
      ),
    );
  }
}

class SettingsScreen extends StatefulWidget {
  final String url;
  final String token;
  final Future<void> Function(String, String) onSave;
  final bool appLock;
  final Future<void> Function(bool) onAppLockChanged;
  final Future<void> Function() onOpenGateway;
  final Future<void> Function() onSyncPending;
  const SettingsScreen({super.key, required this.url, required this.token, required this.onSave, required this.appLock, required this.onAppLockChanged, required this.onOpenGateway, required this.onSyncPending});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late bool lock;
  @override
  void initState() { super.initState(); lock = widget.appLock; }
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('الإعدادات')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          ListTile(title: const Text('بوابة الإدارة الآمنة'), trailing: const Icon(Icons.chevron_right), onTap: widget.onOpenGateway),
          ListTile(title: const Text('مزامنة الأجهزة المعلقة'), trailing: const Icon(Icons.sync), onTap: widget.onSyncPending),
          SwitchListTile(title: const Text('قفل التطبيق'), value: lock, onChanged: (v) async { lock = v; setState(() {}); await widget.onAppLockChanged(v); }),
          const Divider(),
          const Text('• لا تكشف ESXi/FortiGate/SSH للإنترنت.'),
          const Text('• استخدم VPN أو بوابة إدارة آمنة.'),
          const Text('• FortiGate هو البوابة؛ إذا تعطل فقد يتعطل الوصول.'),
        ],
      ),
    );
  }
}

class HistoryScreen extends StatefulWidget {
  final ApiClient client;
  const HistoryScreen({super.key, required this.client});
  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  List<Map<String, dynamic>> entries = [];
  String error = '';
  @override
  void initState() { super.initState(); _load(); }
  Future<void> _load() async {
    try {
      final r = await widget.client.get('/audit');
      if (r.statusCode >= 400) throw Exception('HTTP ${r.statusCode}');
      entries = (jsonDecode(r.body)['entries'] as List? ?? []).map((x) => Map<String, dynamic>.from(x as Map)).toList();
      if (mounted) setState(() => error = '');
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    }
  }
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('سجل العمليات')),
      body: ListView(
        children: [
          if (error.isNotEmpty) ListTile(title: Text(error)),
          ...entries.map((e) => ListTile(
                title: Text('${e['action']} — ${e['result']}'),
                subtitle: Text('${e['target']} · ${e['at']}'),
              )),
        ],
      ),
    );
  }
}
