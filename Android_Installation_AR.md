# تثبيت تطبيق Android — Network Control Center

## 1. التثبيت
- نزّل `Network_Control_Center.apk` (من GitHub Actions artifact `Network-Control-Center-APK` إذا لم يُبنَ محليًا).
- فعّل "تثبيت من مصادر غير معروفة" على الهاتف.
- ثبّت APK.

## 2. الإعداد
1. افتح التطبيق.
2. الإعدادات → اكتب HTTPS URL للخادم داخل VPN (مثال https://10.8.0.2).
3. أدخل Controller API key.
4. احفظ.
5. أضف جهاز: ESXi/FortiGate/Ubuntu.
6. اختبر الاتصال ثم احفظ.

## 3. الاستخدام
- لوحة التحكم تحدّث كل 15 ثانية.
- ESXi قابل للتوسيع لعرض VMs.
- VM متوقفة: زر تشغيل.
- VM تعمل: إعادة تشغيل آمنة/إيقاف آمن عند توفر VMware Tools.

## 4. الأخطاء الشائعة
- HTTP بدلاً من HTTPS: غير مسموح.
- شهادة ESXi غير موثوقة: ثبّت CA على الخادم.
- FortiGate API token غير صحيح: unknown/reachable.
