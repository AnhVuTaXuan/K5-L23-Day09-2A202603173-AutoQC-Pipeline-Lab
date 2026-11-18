"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    c = cfg["second_opinion"]
    conf_th = c["conf"]
    min_area_px = c["min_area_px"]
    fp_conf = c["fp_conf"]
    iou_missing = c["iou_missing"]
    iou_match = c["iou_match"]
    iou_loose = c["iou_loose"]
    n_classes = len(ds.classes)

    issues = []
    for img_p in ds.image_files():
        stem = img_p.stem
        if stem not in preds:
            continue
        raw_lines = ds.read_label_lines(stem)
        if raw_lines is None:
            continue
        size = ds.image_size(stem)
        if size is None:
            continue

        img_w, img_h = size
        labels = ds.valid_boxes(stem)
        img_preds = preds[stem]

        # 1. So từng dự đoán mạnh của model với nhãn (theo thứ tự trong preds[stem])
        for r in img_preds:
            pcls = int(r[0])
            pconf = float(r[1])
            pbox = (float(r[2]), float(r[3]), float(r[4]), float(r[5]))

            if pconf < conf_th:
                continue
            area_px = (pbox[2] * img_w) * (pbox[3] * img_h)
            if area_px < min_area_px:
                continue

            cands = []
            for lb in labels:
                ov = iou_xywh(pbox, lb[1:])
                if ov >= iou_missing:
                    cands.append((lb[0], ov))

            if not cands:
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_MISSING",
                        stem,
                        f"model thấy lớp {pcls} (conf={pconf:.2f}) nhưng nhãn không có box khớp",
                        extra={"conf": round(pconf, 4), "pred_class": pcls},
                    )
                )
                continue

            same_cls = [ov for lc, ov in cands if lc == pcls]
            if same_cls:
                best_same = max(same_cls)
                if best_same < iou_loose:
                    issues.append(
                        Issue(
                            "second_opinion",
                            WARN,
                            "POSSIBLE_LOOSE_BOX",
                            stem,
                            f"box lớp {pcls} có thể lỏng (IoU={best_same:.2f} < {iou_loose})",
                            extra={"conf": round(pconf, 4), "iou": round(best_same, 4)},
                        )
                    )
            else:
                best_other_cls, best_other_iou = max(cands, key=lambda item: item[1])
                if best_other_iou >= iou_match:
                    issues.append(
                        Issue(
                            "second_opinion",
                            WARN,
                            "POSSIBLE_WRONG_CLASS",
                            stem,
                            f"nghi nhầm lớp: nhãn={best_other_cls}, model={pcls} (conf={pconf:.2f}, IoU={best_other_iou:.2f})",
                            extra={
                                "conf": round(pconf, 4),
                                "iou": round(best_other_iou, 4),
                                "label_class": best_other_cls,
                                "pred_class": pcls,
                            },
                        )
                    )

        # 2. So từng dòng nhãn hợp lệ với mọi dự đoán conf >= fp_conf (không lọc diện tích)
        fp_pred_boxes = [
            (float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in img_preds
            if float(r[1]) >= fp_conf
        ]
        for line_no, text in raw_lines:
            try:
                lcls, lcx, lcy, lw, lh = parse_yolo_line(text)
            except ValueError:
                continue
            if lcls < 0 or lcls >= n_classes or lw <= 0 or lh <= 0:
                continue

            lbox = (lcx, lcy, lw, lh)
            best_iou = max((iou_xywh(lbox, pb) for pb in fp_pred_boxes), default=0.0)
            if best_iou < iou_missing:
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_FALSE_POS",
                        stem,
                        f"box nhãn lớp {lcls} không khớp dự đoán nào của model (max IoU={best_iou:.2f})",
                        line=line_no,
                        extra={"iou": round(best_iou, 4), "label_class": lcls},
                    )
                )

    return issues
