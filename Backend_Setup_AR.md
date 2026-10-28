# إعداد خادم التحكم — Network Control Center

## 1. متطلبات الخادم
- جهاز Linux مستقل (وليس VM intended للتعافي).
- Python 3.11+.
- وصول VPN إلى FortiGate وESXi.
- شهادات CA موثوقة لـ ESXi على الخادم (لا تعطيل TLS).

## 2. تثبيت
```bash
cd controller
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 3. متغيرات البيئة
```bash
export NCC_API_KEY='مفتاح-عشوائي-طويل-32-حرف-على-الأقل'
export NCC_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export NCC_DB='/var/lib/ncc/ncc.sqlite3'
export NCC_ENABLE_FORTIGATE_REBOOT='false'
```
احفظها في `/etc/ncc.env` (chmod 600) ولا تضعها في Git.

## 4. تشغيل
```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```
ضع reverse proxy (Nginx/Caddy) أمامه مع HTTPS (شهادة موثوقة) وVPN فقط.

## 5. systemd
استخدم `controller/deploy/ncc-controller.service` (انسخ إلى `/etc/systemd/system/`).

## 6. ESXi
- ثبّت CA chain على الخادم.
- أنشئ حساب ESXi بصلاحية VM Power On / Guest Operations.
- أدخل المسار في `ca_file` (على الخادم).

## 7. FortiGate
- أنشئ API token بصلاحية least-privilege.
- reboot معطل افتراضيًا؛ فعّله فقط بعد التحقق.

## 8. النسخ الاحتياطي
- انسخ ملف SQLite + `/etc/ncc.env` + شهادات.
- أوقف الخدمة قبل النسخ أو استخدم snapshot.
