<p align="center">
  <img src="src/re_sputnik/resources/branding/banner_fa.png" alt="Re:Sputnik" width="760">
</p>

<p align="center">
  <a href="https://t.me/one_andrevich"><img src="https://img.shields.io/badge/Telegram-Join-2CA5E0?style=flat-square&logo=telegram&logoColor=white" alt="Telegram"></a>
  <a href="https://ko-fi.com/D1D11SQNQD"><img src="https://img.shields.io/badge/Ko--fi-Support-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white" alt="Ko-fi"></a>
  <a href="https://nowpayments.io/donation?api_key=decbeb76-30f8-4c6d-ba40-2d2dec7fd888"><img src="https://img.shields.io/badge/Crypto-Donate-2EBE74?style=flat-square&logo=bitcoin&logoColor=white" alt="Crypto donate"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue?style=flat-square" alt="License: GPL-3.0"></a>
</p>

# Re:Sputnik

[English](README.md) · [Русский](README_ru.md) · **فارسی** · [中文](README_cn.md)

> ⚠️ **این یک ترجمهٔ ماشینی است.** نسخهٔ معتبر همان README انگلیسی است؛ از اصلاحات استقبال می‌شود.

**اپلیکیشن دسکتاپ که [Re:HomeProxy](https://github.com/1andrevich/homeproxy-hiddify) را روی روتر OpenWrt نصب و پیکربندی می‌کند — از طریق SSH، بدون نیاز به ترمینال یا LuCI.**

شما آدرس و رمز عبور روتر را وارد می‌کنید؛ بقیهٔ کارها را اپلیکیشن در یک «جادوگر» گرافیکی انجام
می‌دهد: بک‌اند پروکسی و یک هسته را نصب می‌کند، سرورهای شما را وارد می‌کند، مسیریابی و دور زدن DPI
را تنظیم می‌کند و سپس امکان مدیریت Wi-Fi، عیب‌یابی و امنیت را فراهم می‌سازد.

> Re:Sputnik هیچ هستهٔ پروکسی‌ای را همراه خود ندارد — آن‌ها را از منابع رسمی روی روتر نصب می‌کند
> و فقط از طریق SSH/RPC با روتر ارتباط می‌گیرد (`ubus call luci.homeproxy.*`، `uci`، اسکریپت‌های
> خودِ بسته). در اصل یک پلتفرم عمومی «نصب + پیکربندی نرم‌افزار روی OpenWrt» است؛ Re:HomeProxy تنها
> اولین دستورالعمل است.

## دانلود

آخرین نسخه را از صفحهٔ [**Releases**](https://github.com/1andrevich/re-sputnik/releases) دریافت
کنید — بدون نصب‌کننده:

- **Windows** — `Re-Sputnik-windows-x64.exe`، دوبار کلیک کنید.
- **macOS** (Apple Silicon) — `Re-Sputnik-macos-arm64.dmg`، به Applications بکشید.
- **Linux** — `Re-Sputnik-linux-x86_64.AppImage` / `-aarch64.AppImage`، `chmod +x` و اجرا کنید.

نسخه‌ها فعلاً **امضا نشده‌اند**: SmartScreen ویندوز هشدار می‌دهد (More info → Run anyway)؛
Gatekeeper مک اپلیکیشن را قرنطینه می‌کند (راست‌کلیک → Open یا `xattr -dr com.apple.quarantine`).

## امکانات

- **نصب** — معماری روتر و مدیر بسته (opkg/apk) را تشخیص می‌دهد، Re:HomeProxy و یک هستهٔ پروکسی
  (**hiddify-core** یا **sing-box-extended**) را نصب می‌کند و می‌تواند بسته‌ها را برای روترهای روی
  شبکه‌های محدود/کندشده از قبل روی رایانه دانلود کند.
- **سرورها** — وارد کردن اشتراک‌ها (sing-box/Hiddify JSON و Xray/V2Ray JSON)، لینک‌های اشتراکی
  (VLESS/Reality، Hysteria2، Trojan، Shadowsocks…)، `vpn://` و فایل‌های `.conf`
  (WireGuard/AmneziaWG)؛ استخرهای سرعت URLTest.
- **مسیریابی** — حالت‌های آماده (روسیه / چین / ایران / جهانی) بر پایهٔ فهرست‌های Re:filter
  و Russia Inside.
- **دور زدن DPI** — **ByeDPI** داخلی (۴۷ پیش‌تنظیم) و **Zapret 2** (۳۶ پیش‌تنظیم)، به‌علاوه یک
  آزمونگر استراتژی که چند سایت را به‌صورت موازی بررسی می‌کند و نشان می‌دهد چه چیزی واقعاً روی ISP
  شما کار می‌کند.
- **مدیریت** — عیب‌یابی (وضعیت هسته، DNS، مسیرها)، Wi-Fi / LAN / DHCP، رمزها و کلیدهای SSH،
  پشتیبان‌گیری و نگهداری، SQM / UPnP.
- **زبان‌ها** — روسی، انگلیسی، فارسی، چینی. چند پروفایل ذخیره‌شدهٔ روتر.

## سه راه ورود

- **⚡ گام‌به‌گام** — جادوگری خطی که کاربر غیرفنی را در اینترنت، نصب، سرورها و بررسی راهنمایی می‌کند.
- **⚙ پیشرفته** — پیمایش آزاد در بخش‌ها (سرورها، قوانین، عیب‌یابی، Anti-DPI، هسته، امنیت…) برای
  مدیریت دستی.
- **📦 پیش‌نصب بسته‌ها** — دانلود روی رایانه و انتقال به روتر، برای نصب بدون اینترنت روی خودِ روتر.

هر حالت پیکربندی فعلی روتر را برمی‌دارد و از صفر شروع نمی‌کند.

## معماری (کوتاه)

```
UI (customtkinter)          صفحه‌های جادوگر و تنظیمات؛ روند نصب را پیش می‌برند
engine/*                    منطق هر قابلیت (نصب، نودها، قوانین، ByeDPI، Zapret، عیب‌یابی…)
RouterClient (paramiko)     تنها درِ ورود به روتر: اسکریپت‌های داخلی، ubus، uci
Secrets (keyring)           اعتبارنامه‌های روتر در جاکلیدی سیستم‌عامل
```

دستورها در هر اتصال یکی‌یکی اجرا می‌شوند تا درخواست‌های هم‌زمان توسط سرویس SSH روتر قطع نشوند. هیچ
تله‌متری‌ای وجود ندارد؛ اعتبارنامه‌ها هرگز دستگاه شما را ترک نمی‌کنند.

## پشتهٔ فناوری

پایتون خالص + چند کتابخانه — بدون web/HTML/CSS/JS:

| لایه | کتابخانه |
|------|---------|
| رابط کاربری | customtkinter (Tk) |
| ارتباط با روتر | paramiko (SSH) |
| اعتبارنامه‌ها | keyring (جاکلیدی سیستم‌عامل) |
| آیکن‌ها | Lucide/Phosphor (رابط) + Simple Icons (برندها)، تبدیل SVG→PNG هنگام ساخت |

## توسعه

```sh
python -m venv .venv
. .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m re_sputnik
pytest -q                     # تست‌ها + بررسی کامپایل
```

CI در هر push تست‌ها را اجرا می‌کند ([`test.yml`](.github/workflows/test.yml))؛ ساخت چندسکویی
بر اساس درخواست در [`build.yml`](.github/workflows/build.yml) است؛ انتشارهای دارای تگ (`vX.Y.Z`)
همهٔ سکوها را می‌سازند و از طریق [`release.yml`](.github/workflows/release.yml) در صفحهٔ Releases
منتشر می‌شوند. روند مشارکت در [`CONTRIBUTING.md`](CONTRIBUTING.md) آمده است (Developer Certificate
of Origin).

## اطلاعیهٔ علائم تجاری

وابسته به یا تأییدشده توسط YouTube، Telegram، Discord، Meta یا Hiddify نیست. لوگوهای سرویس‌ها
علائم تجاری صاحبان‌شان هستند و فقط برای شناسایی سرویس‌ها استفاده می‌شوند.

## حمایت از پروژه

اگر Re:Sputnik برایتان مفید است، یک ⭐ کمک می‌کند — یا مستقیماً از توسعه حمایت کنید:

<a href="https://ko-fi.com/D1D11SQNQD" target="_blank"><img height="40" src="https://storage.ko-fi.com/cdn/kofi5.png?v=6" alt="حمایت در Ko-fi"></a>
&nbsp;
<a href="https://nowpayments.io/donation?api_key=decbeb76-30f8-4c6d-ba40-2d2dec7fd888" target="_blank" rel="noreferrer noopener"><img src="https://nowpayments.io/images/embeds/donation-button-white.svg" alt="کمک مالی با ارز دیجیتال و بیت‌کوین از طریق NOWPayments"></a>

پرسش‌ها و به‌روزرسانی‌ها — [Telegram](https://t.me/one_andrevich).

## مجوز

Re:Sputnik **نرم‌افزار آزاد** تحت **GNU General Public License v3.0** (GPLv3) است: می‌توانید آن را
با این شرایط استفاده، مطالعه، تغییر و به‌اشتراک بگذارید. متن کامل در [`LICENSE`](LICENSE) و اسناد
اشخاص ثالث در [`NOTICE`](NOTICE) است.

Re:Sputnik برنامه‌ای جدا از **Re:HomeProxy** (آن هم تحت GPL) است: از طریق SSH/RPC با روتر ارتباط
می‌گیرد و سورس Re:HomeProxy را همراه یا لینک نمی‌کند. همهٔ وابستگی‌های شخص ثالث تحت مجوزهای مجاز یا
copyleft ضعیف هستند (MIT/BSD/HPND/MPL-2.0؛ paramiko تحت LGPL-2.1) که با GPLv3 سازگارند. مشارکت‌ها
تحت Developer Certificate of Origin پذیرفته می‌شوند — به [`CONTRIBUTING.md`](CONTRIBUTING.md)
مراجعه کنید.
