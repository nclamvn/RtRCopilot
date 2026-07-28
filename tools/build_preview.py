#!/usr/bin/env python3
"""Sinh RtR_Copilot_UI_Preview.html từ ui.html + lớp giả lập API.

Preview là bản double-click mở được, không cần server: nó nhúng sẵn một ít record
THẬT trích từ gói và thay window.fetch bằng lớp giả lập. Dùng để soi giao diện.

Chạy tự động trong tools/rebuild_all.sh · không sửa tay file preview.
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PILOT = ROOT / "phase1_pilot"
sys.path.insert(0, str(PILOT))
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["COPILOT_PACK"] = "staff"
import copilot_server as cs   # noqa: E402

TERMS = ["14 kg", "1-4-14", "Part 107", "2000 nits", "1800 nits", "DA-26-616A1", "sáng chế",
         "OmniSight", "Sky Watch", "LEGACY", "Nghị định 30/2020", "IP54", "thành lập năm 2014",
         "15 km", "sales brief"]

sample, seen = [], set()
for t in TERMS:
    for r in cs.RECORDS:
        if t.lower() in r["content"].lower() and r["record"] not in seen:
            sample.append({k: r.get(k) for k in
                           ("record", "content", "domain", "tier", "status",
                            "kernel_ref", "source", "effective_date")})
            seen.add(r["record"])
            break

GAPS = [{"q": "Chính sách nghỉ phép công ty thế nào?", "count": 3,
         "variants": ["Chế độ nghỉ phép năm bao nhiêu ngày?", "Nghỉ phép được mấy ngày một năm?"],
         "last": "2026-07-26"},
        {"q": "Lịch xe đưa đón nhà máy?", "count": 1, "variants": [], "last": "2026-07-23"}]
AUDIT = [{"t": "2026-07-27T09:14:02", "q": "Payload Hera hiện tại bao nhiêu?",
          "a": "HERA có sức nâng tối đa 30 lbs (14 kg), gấp 10 lần drone cùng cỡ. [CAND.1.005]",
          "mode": "MOCK", "gate": "MOCK LOOKUP"},
         {"t": "2026-07-26T16:40:11", "q": "Chính sách nghỉ phép công ty thế nào?",
          "a": "SOT chưa có thông tin khớp câu hỏi này.", "mode": "MOCK", "gate": "HONEST NULL"},
         {"t": "2026-07-26T11:02:55", "q": "FCC exemption là gì?",
          "a": "Ngày 22/06/2026 FCC ban hành DA-26-616A1 miễn trừ Hera. [CAND.2.024]",
          "mode": "MOCK", "gate": "MOCK LOOKUP"}]

SHIM = """<script>
/* PREVIEW SHIM · xem giao diện không cần server · record là bản THẬT trích từ gói.
   Sinh tự động bởi tools/build_preview.py · đừng sửa tay file này. */
const __RECS=%s, __GAPS=%s, __AUDIT=%s;
const __n=s=>s.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/đ/g,'d');
function __search(q){const t=__n(q).match(/[a-z0-9]+/g)||[];
return __RECS.map(r=>[t.filter(x=>x.length>2&&__n(r.content+' '+r.record).includes(x)).length,r])
.filter(x=>x[0]>0).sort((a,b)=>b[0]-a[0]).map(x=>x[1]);}
window.fetch=async(u,o)=>{const j=x=>({json:async()=>x,status:200,headers:{get:()=>'application/json'}});
if(u.startsWith('/health'))return j({ok:true,mode:'MOCK',pack:'staff',model:null,
  records_loaded:%d,pack_date:'%s · preview '+__RECS.length+' record mẫu'});
if(u.startsWith('/api/gaps'))return j({groups:__GAPS});
if(u.startsWith('/api/audit'))return j({events:__AUDIT});
if(u.startsWith('/api/usedby'))return j({uses:[{t:'2026-07-27T09:14:02',q:'Payload Hera hiện tại bao nhiêu?'}]});
if(u.startsWith('/api/search'))return j({results:__search(decodeURIComponent(u.split('q=')[1]||'')).slice(0,10)});
if(u.startsWith('/api/record')){const id=decodeURIComponent(u.split('id=')[1]||'');
  return j(__RECS.find(r=>r.record===id)||{error:'không có trong bản preview'});}
if(u.startsWith('/api/chat')){const m=JSON.parse(o.body).messages,q=m[m.length-1].content,h=__search(q);
  if(!h.length)return j({answer:'SOT chưa có thông tin khớp câu hỏi này (bản preview chỉ nhúng '+__RECS.length+' record mẫu).\\nGAP: '+q});
  const r=h[0];return j({answer:'[MOCK · máy tra cứu · chưa nối API]\\n\\n'+r.content+'\\n\\n['+r.record+
    (r.kernel_ref&&r.kernel_ref!=='null'?' · '+r.kernel_ref:'')+']'});}
return j({error:'preview không có endpoint này'});};
</script>""" % (json.dumps(sample, ensure_ascii=False), json.dumps(GAPS, ensure_ascii=False),
                json.dumps(AUDIT, ensure_ascii=False), len(cs.RECORDS), cs.PACK_DATE)

ui = (PILOT / "ui.html").read_text(encoding="utf-8")
ui = ui.replace("<title>RtR Copilot</title>", "<title>RtR Copilot · UI Preview</title>")
ui = ui.replace("<script>", SHIM + "\n<script>", 1)
out = ROOT / "RtR_Copilot_UI_Preview.html"
out.write_text(ui, encoding="utf-8")
print(f"preview: {len(ui)} bytes · {len(sample)} record mẫu")
