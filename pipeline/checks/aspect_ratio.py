"""CHECK MỞ RỘNG (+3 thưởng) — Phát hiện box lệch tỉ lệ khung hình bất thường (aspect ratio).

Test:  pytest tests/test_aspect_ratio.py -q

Một box quá dẹt hoặc quá mảnh (tỉ lệ pixel max(w_px/h_px, h_px/w_px) > max_ratio)
thường là lỗi kéo nhầm biên, vật bị cắt sát mép ảnh, hoặc cột/biển báo bị gán nhầm.
Check chỉ phát cảnh báo mức WARN (không tự xoá) để người duyệt kiểm tra bằng mắt.

Ngưỡng đọc từ `cfg.get("aspect_ratio", {})`:
- `max_ratio` (mặc định 6.0): tỉ lệ tối đa giữa cạnh dài và cạnh ngắn (tính theo pixel
  nhờ `ds.image_size(stem)` để không bị méo trên ảnh không vuông).
"""
from ..common import WARN, Issue, parse_yolo_line

DEFAULT_MAX_RATIO = 6.0


def run(ds, cfg):
    ar_cfg = cfg.get("aspect_ratio", {})
    max_ratio = float(ar_cfg.get("max_ratio", DEFAULT_MAX_RATIO))
    n_classes = len(ds.classes)

    issues = []
    for lf in ds.label_files():
        stem = lf.stem
        lines = ds.read_label_lines(stem)
        if not lines:
            continue
        size = ds.image_size(stem)

        for line_no, text in lines:
            try:
                cid, _cx, _cy, w, h = parse_yolo_line(text)
            except ValueError:
                continue
            if cid < 0 or cid >= n_classes or w <= 0 or h <= 0:
                continue

            if size is not None:
                img_w, img_h = size
                w_px, h_px = w * img_w, h * img_h
            else:
                w_px, h_px = w, h

            if w_px <= 0 or h_px <= 0:
                continue

            ratio = max(w_px / h_px, h_px / w_px)
            if ratio > max_ratio:
                extra = {"aspect_ratio": round(ratio, 2)}
                if size is not None:
                    extra["size_px"] = [round(w_px, 1), round(h_px, 1)]
                issues.append(
                    Issue(
                        "aspect_ratio",
                        WARN,
                        "BOX_EXTREME_AR",
                        stem,
                        f"tỉ lệ khung hình box bất thường ({ratio:.2f}:1 > {max_ratio:g}:1)",
                        line=line_no,
                        extra=extra,
                    )
                )

    return issues
