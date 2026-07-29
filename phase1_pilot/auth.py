#!/usr/bin/env python3
"""Tài khoản và phân quyền · RtR Copilot. Zero-dependency (chỉ thư viện chuẩn Python).

Luồng Lâm chốt 29/07/2026:
  1. Nhân viên tự đăng ký bằng email công ty (@rtrobotics.com / @rtrobotics.me).
  2. Một thư kích hoạt gửi về chính hộp thư đó. Bấm link mới thành tài khoản thật.
  3. Vào ứng dụng thì MẶC ĐỊNH quyền thấp nhất: nhân viên.
  4. Quản trị viên (Lâm) chủ động nâng vai: nhân viên → lãnh đạo → quản trị.

Ba vai · một chiều tăng dần:
  nhanvien  hỏi, tra cứu gói chung, sinh tài liệu nội bộ, báo sai, đề xuất fact
  lanhdao   + đọc nội dung hạn chế (giá vốn), sinh công văn pháp nhân,
              duyệt ca báo sai, xem thống kê tổng hợp (KHÔNG kèm tên người hỏi)
  quantri   + ghi vào kernel, xem câu hỏi kèm tên người, quản trị tài khoản

VÌ SAO EMAIL LÀ CỔNG: ứng dụng không tự biết ai là nhân viên RtR. Thứ duy nhất
chứng minh được mà không cần Lâm gõ tay từng người là "người này nhận được thư ở
hộp thư công ty". Đó là bằng chứng đủ để cấp vai THẤP NHẤT, và không đủ cho gì hơn —
nên mọi vai cao hơn đều phải do quản trị viên bấm tay.

BA ĐIỀU HỆ NÀY KHÔNG LÀM ĐƯỢC, ghi ra để không ai tưởng nhầm:
  · Email công ty còn hiệu lực ≠ còn là nhân viên. Người nghỉ việc mà IT chưa khoá
    hộp thư vẫn đăng ký được. Chống bằng việc admin rà danh sách, không bằng code.
  · Không có xác thực hai lớp. Ai lấy được mật khẩu là vào được.
  · Mật khẩu băm scrypt nên không đọc ngược được, nhưng file accounts.json vẫn là
    tài sản nhạy cảm: quyền 0600, không commit, không sao ra máy khác.
Vì ba điều trên, server vẫn phải nằm trong mạng nội bộ.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCOUNTS = HERE / "accounts.json"
SECRET_FILE = HERE / ".session_secret"

# ---------------------------------------------------------------- cấu hình
def _env_list(name, default):
    raw = os.environ.get(name, "").strip()
    return [x.strip().lower() for x in raw.split(",") if x.strip()] or default

# Tên miền được phép tự đăng ký. Ngoài danh sách này thì từ chối, không có ngoại lệ
# trừ email quản trị viên gốc (COPILOT_ADMIN_EMAIL).
DOMAINS = _env_list("COPILOT_EMAIL_DOMAINS", ["rtrobotics.com", "rtrobotics.me"])

# Hộp thư DÙNG CHUNG · chặn đăng ký. Ba hộp đầu có thật trong SOT (L3F.1.0xx: info@,
# sales@, support@ là contact công khai in trên website). Nhiều người cùng đọc được
# một hộp thư dùng chung, nên "nhận được thư kích hoạt" không còn chứng minh danh tính.
SHARED = set(_env_list("COPILOT_EMAIL_BLOCK", [
    "info", "sales", "support", "contact", "hello", "admin", "root",
    "noreply", "no-reply", "postmaster", "webmaster", "abuse", "billing",
    "hr", "office", "team", "all", "everyone",
]))

ADMIN_EMAIL = os.environ.get("COPILOT_ADMIN_EMAIL", "").strip().lower()

TOKEN_TTL_H = int(os.environ.get("COPILOT_TOKEN_GIO", "12"))     # phiên sống 12 giờ
ACTIVATE_TTL_H = int(os.environ.get("COPILOT_KICHHOAT_GIO", "24"))  # link kích hoạt 24 giờ
# Lời mời tay sống lâu hơn: link được trao qua Zalo hoặc đưa tận tay, người nhận có
# thể đang đi công tác. 24 giờ là quá ngắn cho một thao tác con người.
MOI_TTL_H = int(os.environ.get("COPILOT_MOI_GIO", "72"))
MIN_PW = 10

VAI = ("nhanvien", "lanhdao", "quantri")
BAC = {"nhanvien": 1, "lanhdao": 2, "quantri": 3}

# Bảng hành động → vai tối thiểu. Đây là NGUỒN SỰ THẬT DUY NHẤT về phân quyền;
# mọi endpoint hỏi bảng này chứ không tự viết điều kiện if riêng — điều kiện rải rác
# là cách chắc chắn nhất để một chỗ quên cập nhật khi luật đổi.
QUYEN = {
    "hoi":                 "nhanvien",
    "tra_cuu":             "nhanvien",
    "bao_sai":             "nhanvien",
    "de_xuat_fact":        "nhanvien",
    "sinh_tai_lieu":       "nhanvien",   # fact-sheet, slide card, sales brief
    "doc_han_che":         "lanhdao",    # giá vốn linh kiện + tên nhà cung cấp
    "sinh_cong_van":       "lanhdao",    # văn bản mang tư cách pháp nhân + chữ ký CEO
    "duyet_bao_sai":       "lanhdao",
    "xem_thong_ke":        "lanhdao",    # số liệu tổng hợp, KHÔNG kèm tên
    "xem_ten_nguoi_hoi":   "quantri",    # Lâm chốt: chỉ quản trị viên thấy ai hỏi gì
    "quan_tri_nguoi_dung": "quantri",
    "ghi_kernel":          "quantri",
}

_LOCK = threading.Lock()
_NHIP = {}          # chống dò: (khoa) -> [mốc thời gian]


def now():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or now()).isoformat(timespec="seconds")


# ---------------------------------------------------------------- lưu trữ
def _doc():
    if not ACCOUNTS.exists():
        return {"schema": "1.0", "accounts": []}
    try:
        return json.loads(ACCOUNTS.read_text(encoding="utf-8"))
    except Exception:
        return {"schema": "1.0", "accounts": []}


def _ghi(doc):
    tmp = ACCOUNTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(ACCOUNTS)      # thay nguyên tử · không để lại file rỗng khi ghi dở
    os.chmod(ACCOUNTS, 0o600)


def tat_ca():
    return _doc()["accounts"]


def tim(email):
    e = (email or "").strip().lower()
    return next((a for a in tat_ca() if a["email"] == e), None)


def _luu(acc):
    with _LOCK:
        doc = _doc()
        for i, a in enumerate(doc["accounts"]):
            if a["email"] == acc["email"]:
                doc["accounts"][i] = acc
                break
        else:
            doc["accounts"].append(acc)
        _ghi(doc)


# ---------------------------------------------------------------- mật khẩu
# scrypt là lựa chọn đầu (memory-hard, chống dò bằng GPU tốt hơn). NHƯNG nó do
# OpenSSL cung cấp, mà macOS bản hệ thống dựng trên LibreSSL — LibreSSL KHÔNG có
# scrypt, nên hashlib.scrypt không tồn tại trên đúng cái máy chạy pilot.
# Phát hiện 29/07 khi bộ test dừng giữa chừng ở máy Lâm.
#
# Nên có đường lùi pbkdf2_hmac: luôn có trong thư viện chuẩn, không phụ thuộc
# OpenSSL. Yếu hơn scrypt trước GPU nhưng vẫn là KDF đúng nghĩa, và yếu hơn nhiều
# vẫn hơn hẳn "không chạy được". Chuỗi lưu ghi RÕ thuật toán ở đầu để một hash tạo
# bằng cách này vẫn kiểm được bằng cách kia.
CO_SCRYPT = hasattr(hashlib, "scrypt")
PBKDF2_VONG = int(os.environ.get("COPILOT_PBKDF2_VONG", "600000"))


def bam(pw, salt=None, ep_pbkdf2=False):
    salt = salt or secrets.token_bytes(16)
    if CO_SCRYPT and not ep_pbkdf2:
        n, r, p = 2 ** 14, 8, 1
        h = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
        return f"scrypt${n}${r}${p}${salt.hex()}${h.hex()}"
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_VONG, 32)
    return f"pbkdf2${PBKDF2_VONG}${salt.hex()}${h.hex()}"


def kdf_cua(luu):
    return (luu or "").split("$", 1)[0]


def kiem_duoc(luu):
    """Máy này có kiểm được hash kiểu đó không · dùng để báo lỗi cho ĐÚNG nguyên nhân."""
    k = kdf_cua(luu)
    return k == "pbkdf2" or (k == "scrypt" and CO_SCRYPT)


def khop_mat_khau(pw, luu):
    try:
        phan = luu.split("$")
        if phan[0] == "pbkdf2":
            _, it, salt, h = phan
            thu = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it), 32)
        elif phan[0] == "scrypt":
            _, n, r, p, salt, h = phan
            thu = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt),
                                 n=int(n), r=int(r), p=int(p), dklen=32)
        else:
            return False
        return hmac.compare_digest(thu.hex(), h)
    except Exception:
        return False


# ---------------------------------------------------------------- phiên
def _secret():
    env = os.environ.get("COPILOT_SECRET", "").strip()
    if env:
        return env.encode()
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        os.chmod(SECRET_FILE, 0o600)
    return SECRET_FILE.read_text(encoding="utf-8").strip().encode()


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def tao_token(acc):
    """Token tự chứa · không cần bộ nhớ phiên phía server, sống qua restart.

    Có trường `ver`: MỖI LẦN đổi vai hoặc khoá tài khoản, ver tăng, làm CHẾT ngay
    mọi token đã phát. Không có nó thì admin hạ vai một người mà người đó vẫn giữ
    quyền cũ tới hết 12 giờ — đúng kiểu chế độ suy biến âm thầm.
    """
    exp = int(time.time()) + TOKEN_TTL_H * 3600
    than = f"{acc['email']}|{acc['quyen']}|{acc.get('ver', 1)}|{exp}"
    sig = hmac.new(_secret(), than.encode(), hashlib.sha256).digest()
    return _b64(than.encode()) + "." + _b64(sig)


def doc_token(tok):
    """Trả (acc|None, loi). Không tin gì trong token ngoài chữ ký."""
    try:
        p, s = (tok or "").split(".", 1)
        than = _unb64(p).decode()
        sig = hmac.new(_secret(), than.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(s), sig):
            return None, "Phiên không hợp lệ"
        email, quyen, ver, exp = than.split("|")
        if int(exp) < time.time():
            return None, "Phiên đã hết hạn · đăng nhập lại"
        acc = tim(email)
        if not acc:
            return None, "Tài khoản không còn"
        if acc["trang_thai"] != "hoat_dong":
            return None, "Tài khoản đang bị khoá"
        if int(ver) != acc.get("ver", 1):
            # Vai đổi hoặc tài khoản bị khoá rồi mở lại → token cũ phải chết.
            return None, "Quyền đã thay đổi · đăng nhập lại"
        return acc, ""
    except Exception:
        return None, "Phiên không hợp lệ"


# ---------------------------------------------------------------- chống dò
def nhip_ok(khoa, so_lan, trong_giay):
    """Cửa sổ trượt trong bộ nhớ. Mất khi restart — chấp nhận được cho mạng nội bộ;
    mục tiêu là chặn script dò hàng nghìn lần, không phải chặn kẻ tấn công kiên nhẫn."""
    t = time.time()
    with _LOCK:
        moc = [x for x in _NHIP.get(khoa, []) if t - x < trong_giay]
        if len(moc) >= so_lan:
            _NHIP[khoa] = moc
            return False
        moc.append(t)
        _NHIP[khoa] = moc
        return True


# ---------------------------------------------------------------- email
def _smtp_cfg():
    return {
        "host": os.environ.get("COPILOT_SMTP_HOST", "").strip(),
        "port": int(os.environ.get("COPILOT_SMTP_PORT", "465")),
        "user": os.environ.get("COPILOT_SMTP_USER", "").strip(),
        "pw":   os.environ.get("COPILOT_SMTP_PASS", "").strip(),
        "from": os.environ.get("COPILOT_SMTP_FROM", "").strip()
                or os.environ.get("COPILOT_SMTP_USER", "").strip(),
    }


def smtp_san_sang():
    c = _smtp_cfg()
    return bool(c["host"] and c["user"] and c["pw"])


def gui_mail(den, tieu_de, than):
    """Trả (ok, loi). Chưa cấu hình SMTP thì KHÔNG âm thầm coi như gửi được."""
    c = _smtp_cfg()
    if not smtp_san_sang():
        if os.environ.get("COPILOT_MAIL_DEV") == "1":
            print("\n" + "=" * 66)
            print(f"[MAIL DEV · KHÔNG GỬI THẬT] tới {den}\n{tieu_de}\n\n{than}")
            print("=" * 66 + "\n", flush=True)
            return True, ""
        return False, "Máy chủ chưa cấu hình gửi thư · báo quản trị viên"
    msg = EmailMessage()
    msg["Subject"] = tieu_de
    msg["From"] = c["from"]
    msg["To"] = den
    msg.set_content(than)
    try:
        ctx = ssl.create_default_context()
        if c["port"] == 465:
            with smtplib.SMTP_SSL(c["host"], c["port"], context=ctx, timeout=20) as s:
                s.login(c["user"], c["pw"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(c["host"], c["port"], timeout=20) as s:
                s.starttls(context=ctx)
                s.login(c["user"], c["pw"])
                s.send_message(msg)
        return True, ""
    except Exception as e:
        return False, f"Không gửi được thư: {type(e).__name__}"


# ---------------------------------------------------------------- đăng ký
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def kiem_email(email):
    """Trả (ok, loi_hoac_email_chuan). Sai ở đâu nói rõ ở đó — người dùng gõ lại được."""
    e = (email or "").strip().lower()
    if not _EMAIL_RE.match(e):
        return False, "Địa chỉ email không đúng dạng"
    local, _, dom = e.partition("@")
    if ADMIN_EMAIL and e == ADMIN_EMAIL:
        return True, e                      # quản trị viên gốc · miễn kiểm tên miền
    if dom not in DOMAINS:
        return False, ("Chỉ email công ty đăng ký được · chấp nhận: "
                       + ", ".join("@" + d for d in DOMAINS))
    if local.split("+")[0] in SHARED:
        return False, ("Hộp thư dùng chung không đăng ký được · nhiều người cùng đọc "
                       "được hộp thư này nên thư kích hoạt không chứng minh được bạn là ai. "
                       "Dùng email cá nhân của bạn ở công ty.")
    return True, e


def dang_ky(email, ten, mat_khau, goc_url):
    """Tạo tài khoản chờ kích hoạt + gửi thư. Trả (ok, thong_bao)."""
    ok, e = kiem_email(email)
    if not ok:
        return False, e
    ten = (ten or "").strip()
    if len(ten) < 2:
        return False, "Cần họ tên để người duyệt biết bạn là ai"
    if len(mat_khau or "") < MIN_PW:
        return False, f"Mật khẩu tối thiểu {MIN_PW} ký tự"
    if not nhip_ok("dangky:" + e, 3, 3600):
        return False, "Đã gửi thư kích hoạt · kiểm hộp thư, kể cả mục spam"

    cu = tim(e)
    if cu and cu["trang_thai"] == "hoat_dong":
        return False, "Email này đã có tài khoản · dùng chức năng đăng nhập"

    ma = secrets.token_urlsafe(32)
    la_admin_goc = bool(ADMIN_EMAIL and e == ADMIN_EMAIL)
    acc = {
        "email": e,
        "ten": ten,
        "pw": bam(mat_khau),
        # Mọi người vào bằng vai THẤP NHẤT. Chỉ email quản trị gốc khai trong biến môi
        # trường mới thành quantri — nếu không thì hệ không có ai phân vai được cho ai.
        "quyen": "quantri" if la_admin_goc else "nhanvien",
        "trang_thai": "cho_kich_hoat",
        "ver": 1,
        "ma_kich_hoat": ma,
        "han_kich_hoat": iso(now() + timedelta(hours=ACTIVATE_TTL_H)),
        "tao_luc": iso(),
        "kich_hoat_luc": None,
        "lan_cuoi": None,
        "nguoi_phan_vai": None,
        "phan_vai_luc": None,
        "ghi_chu": "",
    }
    _luu(acc)

    link = f"{goc_url.rstrip('/')}/kichhoat?ma={ma}"
    than = f"""Chào {ten},

Bạn vừa đăng ký RtR Copilot bằng địa chỉ {e}.

Bấm link dưới đây để kích hoạt tài khoản (link sống {ACTIVATE_TTL_H} giờ):

{link}

Sau khi kích hoạt bạn vào được ngay với quyền NHÂN VIÊN: hỏi đáp trên nguồn sự
thật của công ty, tra cứu record, sinh fact-sheet và sales brief, báo bot trả lời
sai. Quyền cao hơn do quản trị viên cấp riêng khi cần.

Một điều nên biết trước khi dùng: câu hỏi của bạn có ghi lại kèm tên, và CHỈ quản
trị viên đọc được phần kèm tên đó. Lãnh đạo chỉ thấy số liệu tổng hợp. Cứ hỏi
những câu bạn nghĩ là ngây thơ — chỗ nào nhiều người hỏi mà bot không trả lời được
chính là chỗ tài liệu công ty đang thiếu, và đó là thông tin quý.

Không phải bạn đăng ký thì bỏ qua thư này, tài khoản sẽ tự hết hạn.

RtR Copilot
"""
    sent, loi = gui_mail(e, "Kích hoạt tài khoản RtR Copilot", than)
    if not sent:
        return False, loi
    return True, f"Đã gửi thư kích hoạt tới {e} · kiểm hộp thư, kể cả mục spam"


def _tim_theo_ma(ma):
    """So sánh mã bằng compare_digest để không rò độ dài khớp qua thời gian phản hồi."""
    ma = (ma or "").strip()
    if not ma:
        return None
    return next((a for a in tat_ca()
                 if a.get("ma_kich_hoat") and hmac.compare_digest(a["ma_kich_hoat"], ma)), None)


def _con_han(acc):
    try:
        return now() <= datetime.fromisoformat(acc["han_kich_hoat"])
    except Exception:
        return False


def trang_thai_ma(ma):
    """Xem một mã dùng để làm gì mà KHÔNG tiêu nó.

    Trả (loai, acc, loi) · loai thuộc: 'kich_hoat' (đã có mật khẩu, chỉ cần bật),
    'dat_mat_khau' (được mời tay, chưa có mật khẩu), None nếu mã hỏng.
    Tách hàm này ra vì trang kích hoạt phải BIẾT nên hiện gì trước khi làm gì —
    gộp vào kich_hoat() thì mở link ra là mã đã tiêu, người được mời hết đường đặt mật khẩu.
    """
    acc = _tim_theo_ma(ma)
    if not acc:
        return None, None, "Mã không đúng hoặc đã dùng rồi"
    if acc["trang_thai"] == "hoat_dong":
        return None, acc, "Tài khoản đã kích hoạt từ trước · đăng nhập được rồi"
    if not _con_han(acc):
        gio = MOI_TTL_H if not acc.get("pw") else ACTIVATE_TTL_H
        return None, acc, f"Link đã quá hạn {gio} giờ · xin cấp lại"
    return ("dat_mat_khau" if not acc.get("pw") else "kich_hoat"), acc, ""


NHAN_VAI = {"nhanvien": "nhân viên", "lanhdao": "lãnh đạo", "quantri": "quản trị viên"}


def kich_hoat(ma, mat_khau=None):
    """Bật tài khoản. Với người được mời tay thì mat_khau là bắt buộc."""
    loai, acc, loi = trang_thai_ma(ma)
    if not loai:
        return (True, loi) if (acc and acc["trang_thai"] == "hoat_dong") else (False, loi)
    if loai == "dat_mat_khau":
        if len(mat_khau or "") < MIN_PW:
            return False, f"Đặt mật khẩu tối thiểu {MIN_PW} ký tự để dùng tài khoản"
        acc["pw"] = bam(mat_khau)
    acc["trang_thai"] = "hoat_dong"
    acc["kich_hoat_luc"] = iso()
    acc["ma_kich_hoat"] = None
    _luu(acc)
    return True, f"Kích hoạt xong · {acc['ten']} vào được với quyền {NHAN_VAI[acc['quyen']]}"


def moi(email, ten, vai, boi, goc_url):
    """Quản trị viên mời tay một người · KHÔNG cần người đó có hộp thư công ty.

    Dùng khi công ty chưa triển khai Workspace: link trao qua Zalo hoặc đưa tận tay.
    Đánh đổi phải nói rõ: ở đường này email KHÔNG còn chứng minh được gì cả —
    thứ chứng minh danh tính là việc quản trị viên tự tay gõ tên người đó vào.
    """
    e = (email or "").strip().lower()
    if not _EMAIL_RE.match(e):
        return False, "Địa chỉ email không đúng dạng", None
    if len((ten or "").strip()) < 2:
        return False, "Cần họ tên để biết đây là ai", None
    if vai not in VAI:
        return False, f"Vai không hợp lệ · chỉ nhận: {', '.join(VAI)}", None
    cu = tim(e)
    if cu and cu["trang_thai"] == "hoat_dong":
        return False, "Người này đã có tài khoản hoạt động", None

    ma = secrets.token_urlsafe(32)
    acc = {
        "email": e, "ten": ten.strip(), "pw": "", "quyen": vai,
        "trang_thai": "cho_kich_hoat", "ver": (cu or {}).get("ver", 0) + 1,
        "ma_kich_hoat": ma, "han_kich_hoat": iso(now() + timedelta(hours=MOI_TTL_H)),
        "tao_luc": iso(), "kich_hoat_luc": None, "lan_cuoi": None,
        "nguoi_phan_vai": boi, "phan_vai_luc": iso(),
        "ghi_chu": f"Mời tay bởi {boi}",
    }
    _luu(acc)
    link = f"{goc_url.rstrip('/')}/kichhoat?ma={ma}"
    # Gửi thư nếu gửi được, nhưng KHÔNG coi việc gửi thất bại là mời thất bại:
    # cả điểm của đường này là chạy được khi hộp thư chưa có.
    da_gui = False
    if smtp_san_sang():
        da_gui, _ = gui_mail(e, "Mời dùng RtR Copilot", f"""Chào {ten},

Bạn được mời dùng RtR Copilot với quyền {NHAN_VAI[vai]}.

Mở link dưới đây để đặt mật khẩu và bắt đầu (link sống {MOI_TTL_H} giờ):

{link}

Câu hỏi của bạn có ghi lại kèm tên, và CHỈ quản trị viên đọc được phần kèm tên đó.
Lãnh đạo chỉ thấy số liệu tổng hợp. Cứ hỏi những câu bạn nghĩ là ngây thơ.

RtR Copilot
""")
    return True, ("Đã tạo lời mời" + (" và gửi thư" if da_gui
                  else " · CHƯA gửi được thư, trao link tận tay")), {"link": link, "da_gui": da_gui}


# ---------------------------------------------------------------- đăng nhập
def dang_nhap(email, mat_khau):
    """Trả (token|None, loi, acc|None)."""
    e = (email or "").strip().lower()
    if not nhip_ok("login:" + e, 10, 900):
        return None, "Sai quá nhiều lần · chờ 15 phút rồi thử lại", None
    acc = tim(e)
    # Hash tạo ở máy CÓ scrypt rồi chuyển accounts.json sang máy KHÔNG có (hoặc ngược
    # lại) thì không kiểm được. Phải báo đúng nguyên nhân: nói "sai mật khẩu" ở đây là
    # đẩy người ta gõ lại mãi một mật khẩu vốn đúng, và giấu mất lỗi hệ thống thật sự.
    if acc and not kiem_duoc(acc["pw"]):
        return None, ("Máy chủ này không kiểm được mật khẩu đã lưu "
                      f"(cần {kdf_cua(acc['pw'])}) · báo quản trị viên đặt lại mật khẩu"), None
    # Cùng một câu báo lỗi cho "không có tài khoản" và "sai mật khẩu": báo tách ra là
    # cho người ngoài dò được ai đang có tài khoản trong công ty.
    sai = "Email hoặc mật khẩu không đúng"
    if not acc or not khop_mat_khau(mat_khau or "", acc["pw"]):
        return None, sai, None
    if acc["trang_thai"] == "cho_kich_hoat":
        return None, "Tài khoản chưa kích hoạt · mở thư kích hoạt trong hộp thư công ty", None
    if acc["trang_thai"] != "hoat_dong":
        return None, "Tài khoản đang bị khoá · liên hệ quản trị viên", None
    acc["lan_cuoi"] = iso()
    _luu(acc)
    return tao_token(acc), "", acc


def doi_mat_khau(acc, cu, moi):
    if not khop_mat_khau(cu or "", acc["pw"]):
        return False, "Mật khẩu hiện tại không đúng"
    if len(moi or "") < MIN_PW:
        return False, f"Mật khẩu mới tối thiểu {MIN_PW} ký tự"
    acc["pw"] = bam(moi)
    acc["ver"] = acc.get("ver", 1) + 1      # đổi mật khẩu → mọi phiên cũ chết
    _luu(acc)
    return True, "Đổi mật khẩu xong · các thiết bị khác phải đăng nhập lại"


# ---------------------------------------------------------------- quản trị
def dat_vai(email, vai, boi):
    if vai not in VAI:
        return False, f"Vai không hợp lệ · chỉ nhận: {', '.join(VAI)}"
    acc = tim(email)
    if not acc:
        return False, "Không có tài khoản này"
    if acc["quyen"] == "quantri" and vai != "quantri":
        con = [a for a in tat_ca()
               if a["quyen"] == "quantri" and a["trang_thai"] == "hoat_dong"
               and a["email"] != acc["email"]]
        if not con:
            # Hạ nốt quản trị viên cuối cùng là tự khoá mình ra ngoài vĩnh viễn:
            # không còn ai phân vai được cho ai, kể cả cho chính mình.
            return False, "Đây là quản trị viên duy nhất còn hoạt động · cấp quyền cho người khác trước"
    acc["quyen"] = vai
    acc["ver"] = acc.get("ver", 1) + 1      # token cũ chết ngay, không chờ hết hạn
    acc["nguoi_phan_vai"] = boi
    acc["phan_vai_luc"] = iso()
    _luu(acc)
    return True, f"{acc['ten']} · vai mới: {vai}"


def dat_khoa(email, khoa, boi):
    acc = tim(email)
    if not acc:
        return False, "Không có tài khoản này"
    if khoa and acc["quyen"] == "quantri":
        con = [a for a in tat_ca()
               if a["quyen"] == "quantri" and a["trang_thai"] == "hoat_dong"
               and a["email"] != acc["email"]]
        if not con:
            return False, "Không khoá được quản trị viên duy nhất còn hoạt động"
    if khoa:
        acc["trang_thai"] = "khoa"
    else:
        acc["trang_thai"] = "hoat_dong" if acc.get("kich_hoat_luc") else "cho_kich_hoat"
    acc["ver"] = acc.get("ver", 1) + 1
    acc["nguoi_phan_vai"] = boi
    acc["phan_vai_luc"] = iso()
    _luu(acc)
    return True, f"{acc['ten']} · {'đã khoá' if khoa else 'đã mở khoá'}"


def cong_khai(acc, day_du=False):
    """Bản rút gọn để trả ra API · KHÔNG bao giờ kèm hash mật khẩu hay mã kích hoạt."""
    d = {"email": acc["email"], "ten": acc["ten"], "quyen": acc["quyen"],
         "trang_thai": acc["trang_thai"]}
    if day_du:
        d.update({"tao_luc": acc.get("tao_luc"), "kich_hoat_luc": acc.get("kich_hoat_luc"),
                  "lan_cuoi": acc.get("lan_cuoi"), "nguoi_phan_vai": acc.get("nguoi_phan_vai"),
                  "phan_vai_luc": acc.get("phan_vai_luc"), "ghi_chu": acc.get("ghi_chu", "")})
    return d


# ---------------------------------------------------------------- cổng quyền
def duoc(acc, hanh_dong):
    """Một câu hỏi duy nhất cả hệ dùng chung: tài khoản này làm được việc kia không."""
    can = QUYEN.get(hanh_dong)
    if can is None:
        return False                        # hành động chưa khai = cấm (fail-closed)
    if not acc:
        return False
    return BAC.get(acc.get("quyen", ""), 0) >= BAC[can]


def co_tai_khoan():
    """Đã có ít nhất một tài khoản hoạt động chưa · quyết định server dùng chế độ nào."""
    return any(a["trang_thai"] == "hoat_dong" for a in tat_ca())


def thong_ke():
    a = tat_ca()
    return {"tong": len(a),
            "hoat_dong": sum(1 for x in a if x["trang_thai"] == "hoat_dong"),
            "cho_kich_hoat": sum(1 for x in a if x["trang_thai"] == "cho_kich_hoat"),
            "khoa": sum(1 for x in a if x["trang_thai"] == "khoa"),
            "theo_vai": {v: sum(1 for x in a if x["quyen"] == v
                                and x["trang_thai"] == "hoat_dong") for v in VAI}}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "thongke":
        print(json.dumps(thong_ke(), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 3 and sys.argv[1] == "vai":
        print(dat_vai(sys.argv[2], sys.argv[3], "dòng lệnh"))
    else:
        print(__doc__)
        print(f"\nBăm mật khẩu: {'scrypt' if CO_SCRYPT else f'pbkdf2-sha256 {PBKDF2_VONG:,} vòng'}"
              + ("" if CO_SCRYPT else "  (máy này không có scrypt · thường là macOS/LibreSSL)"))
        print(f"Tên miền cho phép: {', '.join(DOMAINS)}")
        print(f"Quản trị viên gốc: {ADMIN_EMAIL or '(chưa khai COPILOT_ADMIN_EMAIL)'}")
        print(f"SMTP: {'đã cấu hình' if smtp_san_sang() else 'CHƯA cấu hình'}")
        print(f"Tài khoản: {json.dumps(thong_ke(), ensure_ascii=False)}")
