"""TIP-050: cưỡng chế trục ``use_class`` của TIP-048 ở tầng trả lời.

TIP-048 nới kỷ luật SOT bằng hai tầng mới (``attested_practice`` cho lời chứng
có người đứng tên, ``roadmap_commitment`` cho cam kết có chủ và mốc) kèm trục
``use_class`` ba ngữ cảnh lồng nhau ``attestation ⊂ proposal ⊂ sales``. Kernel
cưỡng chế trục đó khi curate, adapter mang nó vào ``value_payload``, nhưng tầng
trả lời chưa bao giờ đọc tới. Hệ quả: một lời chứng chỉ được phép dùng trong
chào hàng vẫn có thể rơi vào câu trả lời cho hồ sơ tuân thủ. Đó là deviation D3
của TIP-048, và module này đóng nó.

Toàn bộ logic ở đây là thuần: không DB, không IO, không phụ thuộc rag khác, nên
kiểm được bằng test đơn vị chạy ngoài stack.

Thứ tự suy luận cho một record, dừng ở bước đầu tiên có dữ liệu:

1. ``value_payload["use_class"]`` do adapter ghi (nguồn chính xác nhất, đã tính
   cả phần thu hẹp do fact tự khai).
2. ``value_payload["sot_tier"]`` tức tầng kernel gốc. Dùng khi adapter đời cũ
   quên phát ``use_class``. Bước này quan trọng vì TIP-048.1 ánh xạ
   ``attested_practice`` về ``approved_internal`` để vừa ``Literal`` của
   ``PackageRecord``; nếu bỏ qua nó thì một lời chứng sẽ đội lốt tầng phê duyệt
   nội bộ và lọt vào ngữ cảnh chứng thực.
3. ``provenance_level`` của record version (gói đời trước TIP-048, không có
   tầng kernel trong payload).

Không suy được gì thì trả tập rỗng, và tập rỗng nghĩa là KHÔNG dùng được ở ngữ
cảnh nào. Fail closed, không fail open.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

UseClass = Literal["sales", "proposal", "attestation"]

#: Ba ngữ cảnh, xếp từ rộng tới hẹp. Giữ đúng thứ tự của
#: ``kernel/registry/phase_a/provenance_rules.py`` và của
#: ``eval/migrate/kernel_adapter.py``; ba nơi lệch nhau là hỏng doctrine.
USE_CLASSES: tuple[str, ...] = ("sales", "proposal", "attestation")

#: Ngữ cảnh mặc định khi client không nói gì. TIP-048 mục 6 chốt mức GIỮA:
#: ``attestation`` phải được nêu tường minh chứ không suy đoán, và mặc định
#: không được là mức rộng nhất. Hôm nay chưa fact nào tự khai hẹp tới mức chỉ
#: ``sales``, nên chọn ``proposal`` không đổi kết quả của gói eval nào; nó chỉ
#: định trước hành vi cho lần đầu có một fact như vậy.
DEFAULT_USE_CLASS: str = "proposal"

#: Nhãn tiếng Việt của ngữ cảnh, dùng khi phải nói với người vì sao không trả lời.
USE_CLASS_LABELS: dict[str, str] = {
    "sales": "bán hàng",
    "proposal": "đề xuất",
    "attestation": "chứng thực",
}

USE_CLASS_KEY = "use_class"
SOT_TIER_KEY = "sot_tier"

#: Ngữ cảnh SÂU NHẤT mà mỗi tầng được phép vào. Bản sao của kernel
#: ``TIER_MAX_USE``, chép nguyên tên tầng để hai bên đối chiếu được bằng mắt.
TIER_MAX_USE: dict[str, str | None] = {
    "verified_primary": "attestation",
    "verified_secondary": "attestation",
    "approved_internal": "attestation",
    "derived_from_verified": "attestation",
    "attested_practice": "proposal",
    "roadmap_commitment": "proposal",
    "claim": None,
    "flagged": None,
    "placeholder": None,
    "legacy": None,
    "unspecified": None,
}


def normalize_use_class(value: str | None) -> str:
    """Ngữ cảnh hợp lệ, hoặc mặc định. Chuỗi lạ không được coi là ngữ cảnh mới."""
    if isinstance(value, str) and value in USE_CLASSES:
        return value
    return DEFAULT_USE_CLASS


def allowed_for_tier(tier: str | None) -> tuple[str, ...]:
    """Tập ngữ cảnh mà một tầng được phép vào."""
    if not isinstance(tier, str):
        return ()
    deepest = TIER_MAX_USE.get(tier)
    if deepest is None:
        return ()
    return USE_CLASSES[: USE_CLASSES.index(deepest) + 1]


def _declared(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        return ()
    declared = payload.get(USE_CLASS_KEY)
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, Sequence) or isinstance(declared, bytes | bytearray):
        return ()
    return tuple(item for item in USE_CLASSES if item in set(declared))


def _payload_tier(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    tier = payload.get(SOT_TIER_KEY)
    return tier if isinstance(tier, str) else None


def record_use_classes(
    payload: Any,
    *,
    provenance_level: str | None = None,
) -> tuple[str, ...]:
    """Tập ngữ cảnh dùng được của một record, theo thứ tự suy luận ở docstring."""
    declared = _declared(payload)
    if declared:
        return declared
    tier = _payload_tier(payload)
    if tier is not None:
        return allowed_for_tier(tier)
    return allowed_for_tier(provenance_level)


def gate_applies(
    payload: Any,
    *,
    provenance_level: str | None = None,
) -> bool:
    """Trục ``use_class`` có thẩm quyền với record này không.

    Trục này chỉ phân xử giữa các tầng DÙNG ĐƯỢC. Một record ở tầng
    ``claim``/``flagged``/``placeholder``/``legacy`` không thuộc thẩm quyền của
    nó mà thuộc cổng ``require_verified`` có từ TIP-007. Tách bạch như vậy để
    lời gọi ``require_verified=False`` (chủ ý muốn thấy cả claim) không bị
    TIP-050 âm thầm chặn, và để một tầng lạ trong tương lai không biến thành
    lệnh cấm toàn cục.
    """
    if _declared(payload):
        return True
    tier = _payload_tier(payload)
    if tier is not None:
        return TIER_MAX_USE.get(tier) is not None
    if isinstance(provenance_level, str):
        return TIER_MAX_USE.get(provenance_level) is not None
    return False


def record_allows(
    payload: Any,
    *,
    requested: str,
    provenance_level: str | None = None,
) -> bool:
    """Record này có được phép trả lời trong ngữ cảnh ``requested`` không.

    Chỉ gọi khi ``gate_applies`` đã đúng; gọi thẳng cho record ngoài thẩm quyền
    sẽ luôn trả False vì tập ngữ cảnh rỗng.
    """
    return normalize_use_class(requested) in record_use_classes(
        payload,
        provenance_level=provenance_level,
    )


def blocks(
    payload: Any,
    *,
    requested: str,
    provenance_level: str | None = None,
) -> bool:
    """Có phải trục use_class loại record này khỏi ngữ cảnh đang hỏi không.

    Đây là hàm mà tầng trả lời nên dùng: nó gộp sẵn phép kiểm thẩm quyền, nên
    chỗ gọi không thể quên mất một nửa luật.
    """
    if not gate_applies(payload, provenance_level=provenance_level):
        return False
    return not record_allows(
        payload,
        requested=requested,
        provenance_level=provenance_level,
    )


def null_message(requested: str, denied: Sequence[str]) -> str:
    """Câu honest-null khi trục này loại hết bằng chứng của một câu hỏi.

    Im lặng trần là kết quả tệ nhất cho kinh doanh: người hỏi không biết mình
    vừa chạm vào ranh giới nào. Câu này nói đúng ba điều và không nói gì thêm:
    ngữ cảnh nào đang áp, có bao nhiêu ghi nhận liên quan ở tầng bị loại, và
    hỏi lại ở đâu thì thấy nội dung. Không trích nội dung ghi nhận, vì trích ra
    tức là đã dùng nó làm căn cứ trong đúng ngữ cảnh vừa cấm.
    """
    label = USE_CLASS_LABELS.get(normalize_use_class(requested), requested)
    keys = list(denied)
    shown = ", ".join(keys[:5])
    if len(keys) > 5:
        shown = f"{shown} và {len(keys) - 5} ghi nhận khác"
    return (
        f"Ở ngữ cảnh {label}, hệ thống không nhận lời chứng thực hành hay cam "
        f"kết lộ trình làm căn cứ trả lời. Có {len(keys)} ghi nhận liên quan ở "
        f"các tầng đó ({shown}) nhưng chúng chưa có tài liệu gốc nên không đủ "
        f"tư cách dùng ở đây. Hỏi lại ở ngữ cảnh đề xuất hoặc bán hàng để xem "
        f"nội dung các ghi nhận này."
    )
