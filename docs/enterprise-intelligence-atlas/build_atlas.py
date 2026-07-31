from __future__ import annotations

from math import cos, pi, sin
import os
from pathlib import Path

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


ROOT = Path(__file__).resolve().parent
FONT_DIR = Path(os.environ.get('RTR_ATLAS_FONT_DIR', ROOT / 'fonts'))
OUT = Path(os.environ.get('RTR_ATLAS_OUTPUT', ROOT / 'RtR_Enterprise_Intelligence_Atlas.pdf'))

pdfmetrics.registerFont(TTFont('Inter', str(FONT_DIR / 'Inter-Regular.ttf')))
pdfmetrics.registerFont(TTFont('InterSemi', str(FONT_DIR / 'Inter-SemiBold.ttf')))
pdfmetrics.registerFont(TTFont('InterBold', str(FONT_DIR / 'Inter-Bold.ttf')))

W, H = landscape(A4)
BLACK = HexColor('#0A0A0A')
INK = HexColor('#171717')
GRAPHITE = HexColor('#343434')
MID = HexColor('#777777')
SILVER = HexColor('#B8B8B8')
PALE = HexColor('#E8E8E8')
PAPER = HexColor('#F7F7F5')
WHITE = HexColor('#FFFFFF')
TYPE_SCALE = 1.20
GRID_W = 222*mm
GRID_X = (W - GRID_W) / 2
GRID_SHIFT = GRID_X - 22*mm


def style(size=10, leading=None, color=INK, font='Inter', align=TA_LEFT):
    scaled_size = size * TYPE_SCALE
    scaled_leading = (leading if leading is not None else size * 1.3) * TYPE_SCALE
    return ParagraphStyle(
        'x', fontName=font, fontSize=scaled_size, leading=scaled_leading,
        textColor=color, alignment=align, spaceAfter=0, spaceBefore=0,
    )


class Atlas:
    def __init__(self):
        OUT.parent.mkdir(parents=True, exist_ok=True)
        self.c = canvas.Canvas(str(OUT), pagesize=(W, H), pageCompression=1)
        self.c.setTitle('RtR Enterprise Intelligence Atlas')
        self.c.setAuthor('Real-time Robotics / Codex')
        self.c.setSubject('SOT Kernel, enterprise systems, data refinery and AI action architecture')
        self.c.setKeywords('RtR Copilot, SOT, ERP, CRM, HRM, IP, enterprise intelligence, AI')
        self.page = 0
        self.dark = False
        self.grid_state = False

    def new(self, section, title, subtitle='', dark=False):
        if self.page:
            if self.grid_state:
                self.c.restoreState()
                self.grid_state = False
            self.c.showPage()
        self.page += 1
        self.dark = dark
        bg = BLACK if dark else PAPER
        fg = WHITE if dark else INK
        self.c.setFillColor(bg)
        self.c.rect(0, 0, W, H, fill=1, stroke=0)
        self.c.setFillColor(SILVER if dark else MID)
        self.c.setFont('InterSemi', 6.8 * TYPE_SCALE)
        self.c.drawCentredString(W/2, H - 16 * mm, section.upper())
        title_para = Paragraph(title, style(24, 26, fg, 'InterBold', TA_CENTER))
        _, title_h = title_para.wrap(GRID_W, 26*mm)
        title_top = H - 22*mm
        title_para.drawOn(self.c, GRID_X, title_top-title_h)
        if subtitle:
            self.c.setFillColor(SILVER if dark else MID)
            self.c.setFont('Inter', 8.5 * TYPE_SCALE)
            self.c.drawCentredString(W/2, title_top-title_h-5*mm, subtitle)
        self.footer()
        self.c.saveState()
        self.c.translate(GRID_SHIFT, 0)
        self.grid_state = True

    def footer(self):
        fg = Color(1, 1, 1, .4) if self.dark else Color(0, 0, 0, .38)
        self.c.setStrokeColor(fg)
        self.c.setLineWidth(.35)
        self.c.line(GRID_X, 13 * mm, W - GRID_X, 13 * mm)
        self.c.setFillColor(fg)
        self.c.setFont('Inter', 6.5 * TYPE_SCALE)
        self.c.drawCentredString(W/2, 8.5 * mm, 'RTR / ENTERPRISE INTELLIGENCE ATLAS / 2026')
        self.c.drawRightString(W - GRID_X, 8.5 * mm, f'{self.page:02d}')

    def p(self, txt, x, y, w, h, size=10, leading=None, color=None, font='Inter'):
        # Caption/body text in v1 was visually undersized. Scale small copy by
        # 150% and secondary copy by 125%, while retaining the display scale.
        if size <= 7.5:
            size *= 1.5
            leading = (leading * 1.45) if leading else size * 1.22
        elif size < 9:
            size *= 1.25
            leading = (leading * 1.2) if leading else size * 1.22
        color = color or (WHITE if self.dark else INK)
        para = Paragraph(txt, style(size, leading, color, font))
        para.wrapOn(self.c, w, h)
        para.drawOn(self.c, x, y + h - para.height)
        return para.height

    def ct(self, txt, cx, cy, w, h, size=10, leading=None, color=None, font='Inter'):
        """Center text from its real wrapped height, not an estimated baseline."""
        color = color or (WHITE if self.dark else INK)
        para = Paragraph(txt, style(size, leading, color, font, TA_CENTER))
        para.wrapOn(self.c, w, h)
        para.drawOn(self.c, cx - w / 2, cy - para.height / 2)
        return para.height

    def label(self, txt, x, y, color=None, size=6.5):
        if size <= 6.5:
            size *= 1.5
        size *= TYPE_SCALE
        self.c.setFillColor(color or (SILVER if self.dark else MID))
        self.c.setFont('InterSemi', size)
        self.c.drawString(x, y, txt.upper())

    def line(self, x1, y1, x2, y2, color=None, width=.6, dash=None):
        self.c.setStrokeColor(color or (GRAPHITE if self.dark else SILVER))
        self.c.setLineWidth(width)
        self.c.setDash(dash or [])
        self.c.line(x1, y1, x2, y2)
        self.c.setDash([])

    def circle(self, x, y, r, fill=None, stroke=None, width=.7):
        self.c.setFillColor(fill or (GRAPHITE if self.dark else WHITE))
        self.c.setStrokeColor(stroke or (MID if self.dark else SILVER))
        self.c.setLineWidth(width)
        self.c.circle(x, y, r, fill=1, stroke=1)

    def card(self, x, y, w, h, title, body='', code='', dark_card=False):
        if self.dark:
            fill = GRAPHITE if dark_card else HexColor('#1A1A1A')
            stroke = Color(1, 1, 1, .16)
            fg, sub = WHITE, SILVER
        else:
            fill = INK if dark_card else WHITE
            stroke = PALE
            fg, sub = (WHITE, SILVER) if dark_card else (INK, MID)
        self.c.setFillColor(fill)
        self.c.setStrokeColor(stroke)
        self.c.setLineWidth(.6)
        self.c.roundRect(x, y, w, h, 2.2 * mm, fill=1, stroke=1)
        cursor = y + h - 5*mm
        if code:
            self.label(code, x + 5*mm, cursor - 3*mm, sub, 5.8)
            cursor -= 8*mm
        title_para = Paragraph(title, style(10.5, 12, fg, 'InterSemi'))
        _, title_h = title_para.wrap(w - 10*mm, h)
        title_para.drawOn(self.c, x + 5*mm, cursor - title_h)
        cursor -= title_h + 3*mm
        if body:
            body_para = Paragraph(body, style(7.1*1.5, 9.2*1.45, sub, 'Inter'))
            _, body_h = body_para.wrap(w - 10*mm, h)
            if cursor - body_h < y + 4*mm:
                raise ValueError(f'Card overflow: {code or title}')
            body_para.drawOn(self.c, x + 5*mm, cursor - body_h)

    def arrow(self, x1, y1, x2, y2, color=None, width=.8):
        color = color or (MID if self.dark else GRAPHITE)
        self.line(x1, y1, x2, y2, color, width)
        angle = __import__('math').atan2(y2-y1, x2-x1)
        s = 3.2
        self.c.setFillColor(color)
        self.c.setStrokeColor(color)
        pts = []
        for a in (angle, angle + 2.55, angle - 2.55):
            pts.append((x2 + s*cos(a), y2 + s*sin(a)))
        path = self.c.beginPath(); path.moveTo(*pts[0]); path.lineTo(*pts[1]); path.lineTo(*pts[2]); path.close()
        self.c.drawPath(path, fill=1, stroke=0)

    def arrow_nodes(self, x1, y1, r1, x2, y2, r2, color=None, width=.8):
        dx, dy = x2 - x1, y2 - y1
        d = max((dx*dx + dy*dy) ** .5, 1)
        ux, uy = dx/d, dy/d
        self.arrow(x1 + ux*(r1+2), y1 + uy*(r1+2), x2 - ux*(r2+5), y2 - uy*(r2+5), color, width)

    def finish(self):
        if self.grid_state:
            self.c.restoreState()
            self.grid_state = False
        self.c.save()


a = Atlas()

# 01 Cover
a.new('Strategic dossier', 'RTR / INTELLIGENCE ARCHITECTURE', 'A visual atlas of truth, systems and enterprise action', dark=True)
cx, cy = W * .70 - GRID_SHIFT, H * .50
for i, r in enumerate([36, 66, 102, 142]):
    a.c.setStrokeColor(Color(1, 1, 1, .08 + i*.025)); a.c.setLineWidth(.6)
    a.c.circle(cx, cy, r, fill=0, stroke=1)
for i in range(56):
    ang = 2*pi*i/56
    r = 142 if i % 4 else 102
    x, y = cx + r*cos(ang), cy + r*sin(ang)
    a.circle(x, y, 1.15 if i % 4 else 2.1, BLACK, Color(1,1,1,.45), .4)
a.circle(cx, cy, 31, WHITE, WHITE)
a.ct('SOT', cx, cy, 34, 16, 12, 14, BLACK, 'InterBold')
a.p('Một cửa ngõ.<br/>Nhiều hệ thống.<br/><b>Một sự thật có kiểm chứng.</b>', 22*mm, 49*mm, 92*mm, 42*mm, 16, 20, WHITE)
a.label('Prepared for Real-time Robotics', 22*mm, 31*mm, SILVER, 6.5)

# 02 Verdict
a.new('01 / Executive verdict', 'Đánh giá nhanh', 'Tài sản đã tồn tại. Thách thức còn lại là hợp nhất thành năng lực tổ chức.')
a.card(22*mm, 31*mm, 70*mm, 100*mm, 'Tiềm năng chiến lược', '<b>Rất cao.</b><br/><br/>RtR đang sở hữu điều mà nhiều dự án AI thiếu: hệ thống vận hành, corpus ngành, hồ sơ thực tế và phương pháp kiểm định.', 'SIGNAL', True)
a.card(98*mm, 31*mm, 70*mm, 100*mm, 'Luận điểm sản phẩm', 'Copilot không phải chatbot. Nó là lớp tìm kiếm, sự thật, suy luận và hành động nằm trên toàn bộ hệ sinh thái RtR.', 'POSITION')
a.card(174*mm, 31*mm, 70*mm, 100*mm, 'Điều kiện thắng', 'Quản trị dữ liệu, phân quyền, chủ sở hữu miền, provenance và feedback từ kết quả thật phải mạnh hơn tốc độ thêm tính năng.', 'GATE')
a.p('<b>Nhận định:</b> Nếu kết nối đúng, đây có thể trở thành tài sản trí tuệ vận hành tích lũy của doanh nghiệp, không chỉ là một bộ ứng dụng nội bộ.', 22*mm, 139*mm, 222*mm, 18*mm, 11, 14, INK)

# 03 Existing estate
a.new('02 / Existing estate', 'Những mảnh ghép đã có', 'Một nền tài sản hiếm: transactional systems + proprietary corpus + domain practice.', dark=True)
systems = [
    ('MRP', 'Sản xuất / vật tư', 'Giao dịch và năng lực thực thi'),
    ('CRM', 'Khách hàng', 'Quan hệ, cơ hội, lịch sử tiếp cận'),
    ('HRM', 'Nhân sự', 'Năng lực, vai trò, trách nhiệm'),
    ('IP', 'Tài sản trí tuệ', 'Đề tài, sáng chế, hồ sơ, tri thức'),
]
for i,(code,t,b) in enumerate(systems):
    a.card((22+i*57)*mm, 89*mm, 50*mm, 47*mm, t, b, code)
a.card(22*mm, 31*mm, 82*mm, 48*mm, 'THE SKYWATCH', '>500 UAV / gần 300 nhà sản xuất / hàng trăm bài báo / nguồn có provenance', 'PUBLIC INTELLIGENCE', True)
a.card(111*mm, 31*mm, 63*mm, 48*mm, 'DOMAIN DATASETS', 'Nông nghiệp chính xác / xây dựng / đô thị thông minh / hệ sinh thái liên quan', 'SECTOR MEMORY')
a.card(181*mm, 31*mm, 63*mm, 48*mm, 'CORPORATE ARCHIVE', 'Đề án / đề tài / hợp tác lớn / kinh nghiệm thực thi tích lũy', 'INSTITUTIONAL MEMORY')

# 04 Architecture
a.new('03 / Target architecture', 'Từ dữ liệu đến hành động', 'Sáu tầng, mỗi tầng có một trách nhiệm và một cổng kiểm soát.')
layers = [
    ('06', 'ACTION', 'ERP / CRM / HRM / IP / chat / Google Workspace'),
    ('05', 'EXPERIENCE', 'Copilot / search / viewers / document OS / reports'),
    ('04', 'INTELLIGENCE', 'LLM router / agents / forecasting / recommendations'),
    ('03', 'TRUTH KERNEL', 'Registry / evidence / provenance / policy / version'),
    ('02', 'REFINERY', 'Crawl / parse / normalize / dedupe / classify / verify'),
    ('01', 'SOURCES', 'Internal systems / files / web / media / people'),
]
for i,(num,name,desc) in enumerate(layers):
    y = (30 + i*20)*mm
    shade = [INK, GRAPHITE, HexColor('#555555'), HexColor('#888888'), HexColor('#BBBBBB'), HexColor('#E2E2E2')][i]
    fg = WHITE if i < 4 else INK
    a.c.setFillColor(shade); a.c.roundRect(22*mm, y, 222*mm, 15*mm, 2*mm, fill=1, stroke=0)
    a.p(num, 27*mm, y+3*mm, 10*mm, 7*mm, 7, 8, fg, 'InterBold')
    a.p(name, 42*mm, y+3*mm, 42*mm, 7*mm, 8.5, 9, fg, 'InterSemi')
    a.p(desc, 90*mm, y+3*mm, 145*mm, 7*mm, 7.5, 9, fg)

# 05 Truth registry
a.new('04 / SOT kernel', 'Registry nhiều tầng sự thật', 'Không phải mọi câu chữ đều có quyền trở thành sự thật doanh nghiệp.', dark=True)
tiers = [
    ('T0', 'SOURCE', 'Ảnh chụp nguyên bản / file / URL / bản ghi hệ thống', SILVER),
    ('T1', 'CLAIM', 'Mệnh đề được trích xuất, còn phụ thuộc ngữ cảnh', HexColor('#999999')),
    ('T2', 'EVIDENCE', 'Claim đã có locator, nguồn, thời điểm và đối chiếu', HexColor('#777777')),
    ('T3', 'CANONICAL FACT', 'Sự thật được chấp nhận, có owner, version và policy', HexColor('#454545')),
    ('T4', 'DERIVED SIGNAL', 'Chỉ số / suy luận / dự báo, tách khỏi fact', INK),
]
for i,(code,name,desc,col) in enumerate(tiers):
    x=22*mm+i*45*mm
    h=(54 if i == 0 else 36+i*18)*mm
    a.c.setFillColor(col); a.c.roundRect(x, 29*mm, 39*mm, h, 2*mm, fill=1, stroke=0)
    fg=BLACK if i<2 else WHITE
    a.p(code, x+4*mm, 33*mm, 30*mm, 8*mm, 12, 13, fg, 'InterBold')
    a.p(name, x+4*mm, 43*mm, 31*mm, 8*mm, 6.3, 8, fg, 'InterSemi')
    a.p(desc, x+4*mm, 53*mm, 31*mm, h-30*mm, 6.2, 8, fg)
a.p('NGUYÊN TẮC CỐT LÕI', 22*mm, 143*mm, 45*mm, 8*mm, 6.5, 8, SILVER, 'InterSemi')
a.p('Chat, web và LLM tạo <b>claim</b>. Chỉ governance mới nâng claim thành <b>canonical fact</b>. Dự báo luôn phải giữ nhãn dự báo.', 69*mm, 138*mm, 175*mm, 16*mm, 10, 13, WHITE)

# 06 Refinery
a.new('05 / Refinery', 'Cào lọc có chủ đích', 'Giá trị không nằm ở số trang đã cào, mà ở mức tín hiệu được chuyển thành bằng chứng.')
steps = [
    ('01','DISCOVER','Nguồn và không gian quan sát'), ('02','CAPTURE','Snapshot + fingerprint'),
    ('03','EXTRACT','Thực thể + claim + locator'), ('04','CLEAN','Chuẩn hóa + khử trùng'),
    ('05','VERIFY','Đối chiếu + confidence'), ('06','PUBLISH','Registry + policy + owner'),
]
for i,(n,t,b) in enumerate(steps):
    x=(22+i*37)*mm
    a.circle(x+15*mm, 96*mm, 10*mm, INK if i in (0,5) else WHITE, INK if i in (0,5) else SILVER)
    a.ct(n, x+15*mm, 96*mm, 14*mm, 8*mm, 8.5, 10, WHITE if i in (0,5) else INK, 'InterBold')
    if i<5: a.arrow(x+25*mm, 96*mm, x+37*mm, 96*mm, SILVER)
    a.p(t, x, 75*mm, 30*mm, 8*mm, 7.5, 9, INK, 'InterSemi')
    a.p(b, x, 53*mm, 30*mm, 20*mm, 6.4, 8, MID)
qx, qy, qw, qh = 22*mm, 25*mm, 222*mm, 25*mm
a.c.setFillColor(INK); a.c.roundRect(qx, qy, qw, qh, 2*mm, fill=1, stroke=0)
a.label('FAIL CLOSED', qx+5*mm, qy+qh-8*mm, SILVER, 7)
a.p('QUALITY GATE', qx+5*mm, qy+5*mm, 47*mm, 9*mm, 10.5, 12, WHITE, 'InterSemi')
a.line(qx+55*mm, qy+5*mm, qx+55*mm, qy+qh-5*mm, Color(1,1,1,.18), .6)
a.p('Nguồn không rõ / claim thiếu locator / xung đột chưa xử lý / freshness quá hạn -> không được masquerade thành sự thật RtR.', qx+62*mm, qy+5*mm, qw-67*mm, 15*mm, 8.2, 10, SILVER)

# 07 Evolution
a.new('06 / Product position', 'Cửa ngõ tiến hóa thành hệ điều hành', 'Spotlight là điểm bắt đầu hợp lý, không phải giới hạn cuối cùng.', dark=True)
evo=[
    ('01','ENTERPRISE SPOTLIGHT','Tìm đúng người, file, record, sự thật và vị trí.'),
    ('02','KNOWLEDGE OS','Hỏi, kiểm chứng, xem đa định dạng, tạo tài liệu có quản trị.'),
    ('03','INTELLIGENCE OS','Phát hiện tín hiệu, dự báo, đề xuất và theo dõi kết quả.'),
    ('04','ACTION OS','Thực thi qua API có quyền, approval và audit trail.'),
]
for i,(n,t,b) in enumerate(evo):
    x=(22+i*57)*mm; y=(37+i*10)*mm; h=(58+i*12)*mm
    a.c.setFillColor([HexColor('#242424'),HexColor('#333333'),HexColor('#494949'),HexColor('#666666')][i])
    a.c.roundRect(x,y,50*mm,h,2*mm,fill=1,stroke=0)
    a.p(n, x+5*mm,y+h-13*mm,10*mm,7*mm,7,8,SILVER,'InterBold')
    a.p(t, x+5*mm,y+h-27*mm,40*mm,12*mm,8.5,10,WHITE,'InterSemi')
    a.p(b, x+5*mm,y+8*mm,40*mm,h-38*mm,6.8,8.8,SILVER)

# 08 Ecosystem map
a.new('07 / Enterprise ecosystem', 'Copilot ở trung tâm, không nuốt mọi hệ thống', 'Mỗi application giữ domain authority; Copilot thống nhất truy cập, ngữ cảnh và hành động.')
cx,cy=W/2-GRID_SHIFT,H*.49
nodes=[('MRP',-190,78),('CRM',-195,-35),('HRM',-118,-112),('IP',0,-135),('CHAT',122,-112),('WORKSPACE',195,-35),('SKYWATCH',190,78),('ARCHIVE',0,132)]
for name,dx,dy in nodes:
    x,y=cx+dx,cy+dy
    a.arrow_nodes(cx,cy,44,x,y,34,SILVER,.65)
    a.circle(x,y,34,WHITE,GRAPHITE,.9)
    a.ct(name,x,y,74,28,8.8,10.5,INK,'InterSemi')
for r in (42,56):
    a.c.setStrokeColor(PALE);a.c.setLineWidth(.8);a.c.circle(cx,cy,r,fill=0,stroke=1)
a.circle(cx,cy,44,INK,INK)
a.ct('RTR<br/><b>COPILOT</b>',cx,cy,68,38,12,14,WHITE)
a.label('SYSTEM OF INTELLIGENCE + ACTION',22*mm,34*mm,MID,6.5)
a.p('ERP ghi giao dịch. Chat giữ trao đổi. SOT giữ sự thật. Copilot kết nối tất cả bằng policy, evidence và workflow.', 22*mm,20*mm,222*mm,10*mm,9.5,11,INK)

# 09 Intelligence loop
a.new('08 / Strategic intelligence', 'Vòng lặp từ tín hiệu đến kết quả', 'Hệ thống chỉ học khi dự báo được nối lại với kết quả kinh doanh thật.', dark=True)
labels=['SIGNAL','HYPOTHESIS','EVIDENCE','OPPORTUNITY','PROPOSAL','ACTION','OUTCOME','LEARNING']
cx,cy=W*.58-GRID_SHIFT,H*.49; rad=133; node_r=36
points=[]
for i,lbl in enumerate(labels):
    ang=pi/2-2*pi*i/len(labels); x=cx+rad*cos(ang); y=cy+rad*sin(ang)
    points.append((x,y))
for i,(x,y) in enumerate(points):
    x2,y2=points[(i+1)%len(points)]
    a.arrow_nodes(x,y,node_r,x2,y2,node_r,MID,.65)
for i,(lbl,(x,y)) in enumerate(zip(labels,points)):
    a.circle(x,y,node_r,HexColor('#202020'),Color(1,1,1,.34),.8)
    a.ct(f'<font color="#9A9A9A">{i+1:02d}</font><br/>{lbl}',x,y,72,42,7.5,9.5,WHITE,'InterSemi')
a.circle(cx,cy,52,WHITE,WHITE)
a.ct('<b>FEEDBACK</b><br/>LOOP',cx,cy,98,46,13,15,BLACK)
a.p('<b>Ví dụ:</b><br/><br/>Tín hiệu mở rộng nhà máy -> đối chiếu sản phẩm RtR -> account brief -> proposal -> CRM/ERP -> kết quả -> điều chỉnh mô hình cơ hội.',22*mm,48*mm,72*mm,76*mm,9,12,WHITE)

# 10 LLM mesh
a.new('09 / AI infrastructure', 'LLM mesh với fallback thông minh', 'Chọn model theo dữ liệu và nhiệm vụ, không theo thương hiệu.')
criteria=[('SENSITIVITY','Độ mật'),('CAPABILITY','Năng lực'),('COST','Chi phí'),('LATENCY','Độ trễ'),('RESIDENCY','Lưu trú'),('HEALTH','Tình trạng')]
for i,(t,b) in enumerate(criteria):
    x=(22+(i%3)*55)*mm; y=(107-(i//3)*35)*mm
    a.card(x,y,48*mm,31*mm,t,b,f'R{i+1:02d}')
a.card(191*mm,79*mm,53*mm,56*mm,'POLICY ROUTER','Prompt class<br/>Data class<br/>Required evidence<br/>Budget<br/>Fallback chain','CONTROL PLANE',True)
a.arrow(181*mm,106*mm,191*mm,106*mm,GRAPHITE)
models=[('A','REASON'),('B','VISION'),('C','EXTRACT'),('D','PRIVATE')]
for i,(n,t) in enumerate(models):
    x=(25+i*55)*mm
    a.circle(x+18*mm,44*mm,15*mm,INK if i==3 else WHITE,INK)
    a.ct(n,x+18*mm,44*mm,18*mm,10*mm,10,12,WHITE if i==3 else INK,'InterBold')
    a.ct(t,x+18*mm,21*mm,36*mm,9*mm,8.5,10,INK,'InterSemi')
a.p('Một chuẩn output:<br/><b>citation / confidence / policy / audit</b>',191*mm,63*mm,53*mm,14*mm,7.2,9.2,MID)

# 11 Audit
a.new('10 / Multi-role audit', 'AI xây. AI phản biện. Con người chịu trách nhiệm.', 'Vibecode tăng tốc; nghiệm thu nhiều vai giữ chất lượng và trách nhiệm.', dark=True)
roles=[
    ('CONTRACTOR','Thiết kế mục tiêu, acceptance criteria, ranh giới.'),
    ('BUILDER','Triển khai vertical slice, test và evidence.'),
    ('CODE REVIEWER','Tìm lỗi logic, bảo mật, maintainability.'),
    ('QA / RED TEAM','Phá giả định, race, failure mode, dữ liệu độc.'),
    ('DOMAIN CURATOR','Xác nhận sự thật, nguồn và tính phù hợp.'),
    ('HUMAN OWNER','Quyết định phát hành, quyền và hậu quả.'),
]
for i,(t,b) in enumerate(roles):
    x=(22+(i%3)*74)*mm; y=(91-(i//3)*57)*mm
    a.card(x,y,67*mm,46*mm,t,b,f'0{i+1}',dark_card=(i==5))
a.p('Không dùng sự đồng thuận giữa nhiều AI làm bằng chứng đúng. Mọi gate quan trọng phải gắn với test, provenance hoặc người có thẩm quyền.',22*mm,143*mm,222*mm,14*mm,9.5,12,WHITE)

# 12 Journeys
a.new('11 / Enterprise journeys', 'Một cửa ngõ, nhiều vai trò', 'Cùng một truth plane, trải nghiệm và quyền khác nhau.')
journeys=[
    ('EXECUTIVE','Điều gì thay đổi? Vì sao? Hành động nào đáng ưu tiên?'),
    ('SALES','Ai nên tiếp cận? Fit nào? Bằng chứng và proposal nào?'),
    ('ENGINEERING','Spec đúng ở đâu? Revision nào? Tác động thay đổi?'),
    ('OPERATIONS','Vật tư, tiến độ và rủi ro nào đang lệch?'),
    ('RESEARCH','Nguồn nào mới? Claim nào đủ bằng chứng để publish?'),
    ('PEOPLE','Ai có năng lực? Ai được quyền? Ai chịu trách nhiệm?'),
]
for i,(t,b) in enumerate(journeys):
    x=(22+(i%2)*113)*mm; y=(100-(i//2)*42)*mm
    a.card(x,y,106*mm,40*mm,t,b,f'J{i+1:02d}',dark_card=(i==0))
a.p('<b>Một câu hỏi tốt phải có thể đi hết chuỗi:</b> tìm -> hiểu -> kiểm chứng -> mở đúng vị trí -> tạo đầu ra -> phê duyệt -> hành động.',22*mm,145*mm,219*mm,10*mm,10,12,INK)

# 13 Value
a.new('12 / Enterprise value', 'Giá trị tích lũy theo bốn đường', 'Không định giá bằng số prompt. Định giá bằng thời gian, sai số, tốc độ và tài sản học tập.', dark=True)
vals=[
    ('01','TIME','Giảm thời gian tìm, đọc, đối chiếu và soạn lại.'),
    ('02','RISK','Giảm dùng sai version, sai dữ kiện, sai quyền và thiếu audit.'),
    ('03','GROWTH','Phát hiện cơ hội sớm, proposal nhanh, kết nối đúng đối tác.'),
    ('04','MEMORY','Biến kinh nghiệm, kết quả và corpus thành tài sản tái sử dụng.'),
]
for i,(n,t,b) in enumerate(vals):
    x=(22+i*57)*mm
    a.card(x,69*mm,50*mm,66*mm,t,b,n,dark_card=(i==3))
a.p('VALUE = HOURS SAVED + ERRORS AVOIDED + CYCLE TIME REDUCED + OPPORTUNITIES CREATED + KNOWLEDGE RETAINED',22*mm,36*mm,222*mm,17*mm,11,14,WHITE,'InterSemi')

# 14 Moat and risks
a.new('13 / Strategic moat', 'Hào bảo vệ và điểm dễ thất bại', 'Model có thể thay. Dữ liệu, ontology, governance và feedback loop mới là tài sản bền.')
a.label('COMPOUNDING ASSETS',22*mm,137*mm,MID)
moats=['Ontology RtR','Registry có provenance','Corpus ngành','Lịch sử quyết định','Workflow phê duyệt','Outcome feedback']
for i,m in enumerate(moats):
    x=(22+(i%3)*55)*mm; y=(92-(i//3)*46)*mm
    a.card(x,y,49*mm,42*mm,m,'Tích lũy theo sử dụng',f'M{i+1:02d}',dark_card=(i==0))
a.c.setFillColor(INK);a.c.roundRect(185*mm,28*mm,59*mm,106*mm,2*mm,fill=1,stroke=0)
a.label('FAILURE MODES',191*mm,122*mm,SILVER)
risks=['Không có data owner','Web claim lẫn company fact','Agent được quyền quá sớm','Monolith hóa mọi ứng dụng','Không đo outcome thật','Corpus cũ nhưng vẫn trả lời']
risk_top = 114*mm
for i,r in enumerate(risks):
    para = Paragraph(f'{i+1:02d}  {r}', style(10.65, 11, WHITE, 'InterSemi' if i<3 else 'Inter'))
    _, ph = para.wrap(47*mm, 22*mm)
    para.drawOn(a.c, 191*mm, risk_top-ph)
    risk_top -= ph + 2.1*mm
assert risk_top > 31*mm, 'Failure-mode list overflow'
a.p('<b>Kết luận:</b> moat không phải LLM. Moat là khả năng biết điều gì đúng, vì sao đúng, ai được dùng và hành động nào tạo kết quả.',22*mm,22*mm,154*mm,15*mm,10,13,INK)

# 15 Roadmap
a.new('14 / Build sequence', 'Từ hệ sinh thái ứng dụng đến intelligence company', 'Trình tự ưu tiên giảm rủi ro trước khi mở rộng quyền tự động hóa.', dark=True)
phases=[
    ('NOW','FOUNDATION','Copilot TIP 001-009 / identity / SOT / RAG / files / document OS'),
    ('NEXT','GOVERN','Curator / freshness / gaps / design / observability / pilot'),
    ('CONNECT','INTEGRATE','MRP / CRM / HRM / IP / Google Workspace / chat events'),
    ('LEARN','INTELLIGENCE','Industry signals / forecasting / partner and policy proposals'),
    ('SCALE','ACTION','Approved agents / workflow execution / outcome feedback'),
]
for i,(tag,t,b) in enumerate(phases):
    x=(22+i*45)*mm
    a.c.setFillColor(WHITE if i==0 else HexColor('#303030'))
    a.c.roundRect(x,51*mm,39*mm,(58+i*7)*mm,2*mm,fill=1,stroke=0)
    fg=BLACK if i==0 else WHITE; sub=GRAPHITE if i==0 else SILVER
    a.p(tag,x+4*mm,58*mm,31*mm,7*mm,6,8,sub,'InterBold')
    a.p(t,x+2*mm,70*mm,35*mm,11*mm,7.2,9,fg,'InterSemi')
    a.p(b,x+4*mm,84*mm,31*mm,(22+i*7)*mm,6.1,7.8,sub)
a.p('Nguyên tắc: tăng quyền tự động hóa chậm hơn tốc độ tăng bằng chứng, quan sát và khả năng rollback.',22*mm,30*mm,222*mm,12*mm,9.5,12,WHITE)

# 16 Finale
a.new('15 / Final position', 'Doanh nghiệp biết mình biết gì', 'Và cũng biết rõ điều gì chưa đủ bằng chứng để khẳng định.')
cx,cy=W*.72-GRID_SHIFT,H*.49
for r,shade in [(115,PALE),(86,SILVER),(58,MID),(30,INK)]:
    a.circle(cx,cy,r,PAPER,shade,1.0)
for i in range(12):
    ang=2*pi*i/12; x=cx+115*cos(ang); y=cy+115*sin(ang)
    a.circle(x,y,3,INK,INK)
    a.line(cx+30*cos(ang),cy+30*sin(ang),x-4*cos(ang),y-4*sin(ang),SILVER,.5)
a.circle(cx,cy,30,INK,INK)
a.ct('SOT',cx,cy,42,18,11,13,WHITE,'InterBold')
a.p('RTR COPILOT',22*mm,112*mm,90*mm,12*mm,7,9,MID,'InterSemi')
a.p('Enterprise<br/><b>Intelligence<br/>& Action OS</b>',22*mm,58*mm,95*mm,52*mm,21,24,INK)
a.p('Quan sát sớm.<br/>Hiểu đúng.<br/>Quyết định có bằng chứng.<br/>Hành động có kiểm soát.',22*mm,29*mm,82*mm,28*mm,10,13,MID)

a.finish()
print(OUT)
