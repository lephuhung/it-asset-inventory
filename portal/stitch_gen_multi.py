#!/usr/bin/env python3
"""Generate nhiều trang qua Stitch MCP, lưu HTML vào stitch-ref/.

Dùng: python3 stitch_gen_multi.py
Yêu cầu env STITCH_KEY.
"""
import json, os, urllib.request

KEY = os.environ["STITCH_KEY"]
PID = "9228926018004311093"
DS = "assets/082f3f00f61d42f7b034825534dd8216"
URL = "https://stitch.googleapis.com/mcp"
HDRS = {"X-Goog-Api-Key": KEY, "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}

SIDE = ("Same left sidebar as dashboard: white bg, blue square logo 'IT', brand 'Asset Inventory' "
        "with subtitle, nav groups (Tong quan: Dashboard; Quan ly tai san: May tinh, May ma, Token trien khai; "
        "Bao cao: Xuat bao cao, Windows EOL; Van hanh: Audit log, Bao mat tai khoan, Thong bao tuan thu), "
        "user card at bottom with avatar Q, name 'Quan tri vien he thong', role badge 'Admin toan cuc', logout. ")
SHELL = ("Sticky top header bar h-14 with page title and a green Realtime pill on right. "
         "Main content max-width 1320px centered. Light slate-50 bg, white cards with subtle shadow, "
         "blue-600 accent, rounded corners, compact spacing. No horizontal page scroll; tables scroll within their card. ")

PAGES = {
    "machine-detail": SIDE + SHELL + "Machine detail page. Header title 'Chi tiet may'. "
    "Top: a back link 'May tinh'. A 2-column grid: left card 'Thong tin co ban' showing hostname, machine uuid (mono), "
    "trang thai badge (Online/Offline/May ma with colored dot), vong doi badge, loai (Ao/Vat ly), enrolled_at, lan cuoi online; "
    "right card 'Cau hinh hien tai' showing OS name+version+build, CPU model+cores, RAM gb, list of disks (model+capacity), GPU. "
    "Below: card 'Mang & nguoi dung' with table of network interfaces (Card mang, IP, MAC) and the logged user. "
    "Below: card 'Lich su hoat dong' showing a timeline of online/offline events. "
    "Footer note about read-only agent.",
    "ghost-machines": SIDE + SHELL + "Ghost machines report page. Header title 'May ma'. "
    "Intro text: machines with no contact for >30/60/90 days. "
    "Three grouped sections each a card: '>90 ngay' (red, critical), '>60 ngay' (amber), '>30 ngay' (slate). "
    "Each card has a table: Hostname, UUID, Lan cuoi online, So ngay mat lien lac, and a 'Kiem tra' button. "
    "Empty states for groups with no machines. Summary card at top with counts.",
    "reports": SIDE + SHELL + "Reports export page. Header title 'Xuat bao cao'. "
    "A card 'Bao cao danh sach may' with export options: filters (Co quan select, Trang thai select, Tim kiem input), "
    "checkbox 'Hien day du so dien thoai' (hint: chi admin), and a primary button 'Xuat Excel' with download icon. "
    "Below: a preview table card showing a few sample machine rows (Hostname, Trang thai, OS, RAM, Nguoi dung, So dien thoai masked). "
    "Note: moi export duoc ghi vao audit log.",
    "eol": SIDE + SHELL + "Windows EOL report page. Header title 'Bao cao Windows EOL'. "
    "Intro: danh sach may chay Windows sap/da het vong doi. "
    "A summary card: counts by status (Con han, Sap het, Da het). "
    "A table card 'Danh sach may theo EOL': columns Hostname, OS (VD Windows 10 22H2), Ngay EOL, Con lai (days, colored), "
    "Trang thai badge. Rows sorted by soonest EOL. Color coding: red for expired, amber for soon, green for ok.",
    "audit": SIDE + SHELL + "Audit log page (read-only, admin only). Header title 'Audit log'. "
    "Intro: nhat ky append-only + hash chain (phat hien gia mao). "
    "Filter card: action type select, actor search, date range. "
    "Table card 'Nhat ky': columns Thoi gian, Actor, Hanh dong, Doi tuong, IP, Request ID. "
    "A small integrity status badge at top 'Hash chain: OK' (green) or 'Dut chuoi' (red). "
    "Rows monospace request id, timestamp formatted. Footer note about append-only + anchor ky dinh ky.",
    "security": SIDE + SHELL + "Account security page (2FA). Header title 'Bao mat tai khoản'. "
    "Card 'Xac thuc 2 yeu to (TOTP)' with status: chua bat / da bat. "
    "If not enabled: a 'Bat 2FA' button. On enable: a QR code placeholder, otpauth URI, "
    "a 6-digit code input + 'Xac nhan' button, and a list of 10 backup codes (one-time, hashed). "
    "Hint text: tuong thich Google Authenticator / Authy / Microsoft Authenticator. "
    "If enabled: 'Da bat' badge, a 'Tat 2FA' danger button (with confirm). "
    "Note: 2FA bat buoc cho admin (muc 5.3).",
    "compliance": SIDE + SHELL + "Legal compliance notice page. Header title 'Thong bao tuan thu'. "
    "Card 'Thong bao hien hanh' showing the active compliance notice: title, version, effective date, "
    "and the full notice content rendered as markdown (prose): muc dich thu thap, du lieu thu thap "
    "(cau hinh may, online/offline, user dang nhap, IP), khong thu thap (noi dung lien lac, lich su web, phim go, anh man hinh), "
    "thoi han luu tru, ai duoc truy cap, quyen cua nguoi dung. "
    "A 'Toi da doc va dong y' primary button (ghi user_acknowledgments). "
    "Below: 'Lich su phat hanh' list of past notice versions. "
    "Footer: tuan theo ND 13/2023/ND-CP, Luat ATTT 2015, Luat ANM 2018.",
}

def gen(name, prompt):
    body = {"jsonrpc":"2.0","id":1,"method":"tools/call",
            "params":{"name":"generate_screen_from_text",
                      "arguments":{"projectId":PID,"prompt":prompt,
                                   "deviceType":"DESKTOP","designSystem":DS}}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=HDRS, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=300).read().decode()
        d = json.loads(r)
        sc = d.get("result",{}).get("structuredContent",{})
        comps = sc.get("outputComponents",[])
        if not comps:
            return f"ERR {name}: {d.get('result',{}).get('content')}"
        s = comps[0]["design"]["screens"][0]
        url = s["htmlCode"]["downloadUrl"]
        try:
            html = urllib.request.urlopen(url, timeout=30).read()
            open(f"stitch-ref/{name}.html","wb").write(html)
            return f"OK {name}: {len(html)} bytes (id={s.get('id')})"
        except Exception as e:
            return f"download err {name}: {e}"
    except Exception as e:
        return f"ERR {name}: {type(e).__name__} {e}"

if __name__ == "__main__":
    os.makedirs("stitch-ref", exist_ok=True)
    for name, prompt in PAGES.items():
        print(gen(name, prompt))
        print("-"*60)
