"""TIP-050: test đơn vị cho trục use_class ở tầng trả lời.

Oracle cam kết trước khi nối vào ``answering.py``: mỗi case dưới đây mô tả một
hình dạng payload có thật do ``eval/migrate/kernel_adapter.py`` phát ra, hoặc
một hình dạng đời trước còn sống trong DB, kèm phán quyết mong đợi.
"""

from rtr_copilot.rag.use_class import (
    DEFAULT_USE_CLASS,
    USE_CLASS_LABELS,
    USE_CLASSES,
    allowed_for_tier,
    blocks,
    gate_applies,
    normalize_use_class,
    null_message,
    record_allows,
    record_use_classes,
)

VERIFIED = {
    "value": "14 kg",
    "use_class": ["sales", "proposal", "attestation"],
    "sot_tier": "verified_primary",
}
ATTESTED = {
    "claim": "Sao lưu hằng ngày, giữ 30 ngày",
    "use_class": ["sales", "proposal"],
    "sot_tier": "attested_practice",
}
ROADMAP = {
    "claim": "Đạt ISO 27001 quý 2/2027",
    "use_class": ["sales", "proposal"],
    "sot_tier": "roadmap_commitment",
}
#: Adapter đời cũ quên phát use_class nhưng TIP-048.1 đã hạ tầng về
#: approved_internal để vừa Literal. Nếu chỉ nhìn provenance_level thì lời chứng
#: này đội lốt tầng phê duyệt nội bộ và lọt vào ngữ cảnh chứng thực.
ATTESTED_NO_USE_CLASS = {"claim": "Mã hóa AES-256", "sot_tier": "attested_practice"}
#: Gói đời trước TIP-048: không có tầng kernel trong payload.
LEGACY = {"value": "3500 W"}


def test_thu_tu_ngu_canh_khong_duoc_doi():
    assert USE_CLASSES == ("sales", "proposal", "attestation")


def test_mac_dinh_la_muc_giua_theo_packet_tip048():
    """TIP-048 mục 6: attestation phải nêu tường minh, mặc định không rộng nhất."""
    assert DEFAULT_USE_CLASS == "proposal"
    assert normalize_use_class(None) == "proposal"


def test_verified_primary_dung_duoc_moi_ngu_canh():
    for context in USE_CLASSES:
        assert record_allows(VERIFIED, requested=context)
        assert not blocks(VERIFIED, requested=context)


def test_attested_practice_bi_chan_o_ngu_canh_chung_thuc():
    assert not blocks(ATTESTED, requested="sales")
    assert not blocks(ATTESTED, requested="proposal")
    assert blocks(ATTESTED, requested="attestation")


def test_roadmap_commitment_bi_chan_o_ngu_canh_chung_thuc():
    assert not blocks(ROADMAP, requested="proposal")
    assert blocks(ROADMAP, requested="attestation")


def test_sot_tier_chan_duoc_loi_chung_doi_lot_approved_internal():
    assert blocks(
        ATTESTED_NO_USE_CLASS,
        requested="attestation",
        provenance_level="approved_internal",
    )
    assert not blocks(
        ATTESTED_NO_USE_CLASS,
        requested="proposal",
        provenance_level="approved_internal",
    )


def test_goi_doi_truoc_roi_ve_provenance_level():
    assert record_use_classes(LEGACY, provenance_level="approved_internal") == USE_CLASSES
    assert not blocks(LEGACY, requested="attestation", provenance_level="verified_primary")


def test_claim_khong_thuoc_tham_quyen_truc_nay():
    payload = {"claim": "số chưa kiểm chứng"}
    assert not gate_applies(payload, provenance_level="claim")
    assert not blocks(payload, requested="attestation", provenance_level="claim")


def test_fact_tu_khai_hep_hon_thi_bi_thu_hep():
    narrowed = {"value": "x", "use_class": ["sales"], "sot_tier": "verified_primary"}
    assert not blocks(narrowed, requested="sales")
    assert blocks(narrowed, requested="proposal")
    assert blocks(narrowed, requested="attestation")


def test_ngu_canh_la_bi_quy_ve_mac_dinh():
    assert normalize_use_class("attestation ") == DEFAULT_USE_CLASS
    assert normalize_use_class(None) == DEFAULT_USE_CLASS
    assert normalize_use_class("compliance") == DEFAULT_USE_CLASS


def test_cau_honest_null_noi_du_ba_dieu_va_khong_trich_noi_dung():
    message = null_message("attestation", ["L3F.INF.014", "L3F.INF.012"])
    assert "chứng thực" in message
    assert "2 ghi nhận" in message
    assert "L3F.INF.014" in message and "L3F.INF.012" in message
    assert "Argon2id" not in message
    assert "đề xuất" in message


def test_cau_honest_null_gom_khi_qua_nam_ghi_nhan():
    denied = [f"L3F.INF.{index:03d}" for index in range(1, 9)]
    message = null_message("attestation", denied)
    assert "8 ghi nhận" in message
    assert "và 3 ghi nhận khác" in message
    assert "L3F.INF.008" not in message


def test_nhan_ngu_canh_day_du():
    assert set(USE_CLASS_LABELS) == set(USE_CLASSES)


def test_payload_khong_phai_mapping_van_suy_duoc_tu_provenance():
    assert record_use_classes("chuỗi thô", provenance_level="verified_primary") == USE_CLASSES
    assert record_use_classes(None, provenance_level=None) == ()


def test_gia_tri_rac_trong_use_class_bi_bo_qua():
    payload = {"use_class": ["sales", "khach_hang_vip"], "sot_tier": "verified_primary"}
    assert record_use_classes(payload) == ("sales",)


def test_bang_tang_khop_voi_kernel():
    assert allowed_for_tier("verified_primary") == USE_CLASSES
    assert allowed_for_tier("derived_from_verified") == USE_CLASSES
    assert allowed_for_tier("attested_practice") == ("sales", "proposal")
    assert allowed_for_tier("roadmap_commitment") == ("sales", "proposal")
    assert allowed_for_tier("claim") == ()
    assert allowed_for_tier("tang_khong_ton_tai") == ()
    assert allowed_for_tier(None) == ()
