"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line

REMOVE_IMAGE_CODES = {
    "DUP_IMAGE_EXACT",
    "DUP_IMAGE_NEAR",
    "LEAK_TEST",
    "CORRUPT_IMAGE",
    "BAD_SIZE",
}
DROP_LINE_CODES = {
    "BAD_FORMAT",
    "BAD_CLASS_ID",
    "BOX_ZERO",
    "DUP_BOX",
}


def fix(ds, issues, cfg):
    fixes = []
    err_issues = [i for i in issues if i.severity == ERROR]
    if not err_issues:
        return fixes

    # 1. Xoá ảnh lỗi (hỏng, nhỏ, trùng, rò rỉ test) trước
    removed_stems = set()
    to_remove = sorted({i.image for i in err_issues if i.code in REMOVE_IMAGE_CODES})
    for stem in to_remove:
        img_p = ds.image_path(stem)
        lbl_p = ds.label_path(stem)
        existed = False
        if img_p is not None and img_p.exists():
            img_p.unlink()
            existed = True
        if lbl_p.exists():
            lbl_p.unlink()
            existed = True
        removed_stems.add(stem)
        if existed:
            codes = sorted({i.code for i in err_issues if i.image == stem and i.code in REMOVE_IMAGE_CODES})
            fixes.append(
                {
                    "image": stem,
                    "line": "",
                    "action": "remove_image",
                    "before": ",".join(codes),
                    "after": "(đã xoá ảnh và nhãn)",
                }
            )

    # 2. Sửa tên lớp trong data.yaml (tối đa 1 lần)
    if any(i.code == "BAD_CLASS_NAME" for i in err_issues):
        target_names = {idx: name for idx, name in enumerate(cfg["classes"])}
        cur_names = ds.yaml_names()
        if cur_names != target_names:
            data = {}
            if ds.yaml_path.exists():
                data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
            before_names = data.get("names")
            data["names"] = target_names
            ds.yaml_path.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            fixes.append(
                {
                    "image": "data.yaml",
                    "line": "",
                    "action": "rename_classes",
                    "before": str(before_names),
                    "after": str(cfg["classes"]),
                }
            )

    # 3. Ảnh thiếu file nhãn -> KHÔNG tạo file rỗng, chuyển người gán
    missing_stems = sorted(
        {
            i.image
            for i in err_issues
            if i.code == "MISSING_LABEL_FILE" and i.image not in removed_stems
        }
    )
    for stem in missing_stems:
        if not ds.label_path(stem).exists():
            fixes.append(
                {
                    "image": stem,
                    "line": "",
                    "action": "needs_label",
                    "before": "(không có file)",
                    "after": "chuyển người gán",
                }
            )

    # 4. Sửa/xoá từng dòng nhãn theo file (gom theo file và ghi lại 1 lần để giữ đúng số dòng gốc)
    line_codes = defaultdict(lambda: defaultdict(set))
    for i in err_issues:
        if i.image in removed_stems or i.line is None:
            continue
        if i.code in DROP_LINE_CODES or i.code == "BOX_OUT_OF_IMAGE":
            line_codes[i.image][int(i.line)].add(i.code)

    for stem in sorted(line_codes):
        lbl_p = ds.label_path(stem)
        if not lbl_p.exists():
            continue
        raw_lines = lbl_p.read_text(encoding="utf-8", errors="replace").splitlines()
        new_lines = []
        changed = False

        for line_no, raw_ln in enumerate(raw_lines, 1):
            codes = line_codes[stem].get(line_no)
            if not codes:
                new_lines.append(raw_ln)
                continue

            if codes & DROP_LINE_CODES:
                changed = True
                fixes.append(
                    {
                        "image": stem,
                        "line": line_no,
                        "action": "drop_line",
                        "before": raw_ln,
                        "after": "",
                    }
                )
            elif "BOX_OUT_OF_IMAGE" in codes:
                try:
                    cid, cx, cy, w, h = parse_yolo_line(raw_ln)
                except ValueError:
                    changed = True
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_no,
                            "action": "drop_line",
                            "before": raw_ln,
                            "after": "",
                        }
                    )
                    continue

                x1 = max(0.0, min(1.0, cx - w / 2))
                y1 = max(0.0, min(1.0, cy - h / 2))
                x2 = max(0.0, min(1.0, cx + w / 2))
                y2 = max(0.0, min(1.0, cy + h / 2))
                nw, nh = x2 - x1, y2 - y1

                if nw <= 1e-9 or nh <= 1e-9:
                    changed = True
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_no,
                            "action": "drop_line",
                            "before": raw_ln,
                            "after": "",
                        }
                    )
                else:
                    ncx, ncy = (x1 + x2) / 2, (y1 + y2) / 2
                    clipped = f"{cid} {ncx:.6f} {ncy:.6f} {nw:.6f} {nh:.6f}"
                    new_lines.append(clipped)
                    changed = True
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_no,
                            "action": "clip_box",
                            "before": raw_ln,
                            "after": clipped,
                        }
                    )

        if changed:
            content = "\n".join(new_lines) + ("\n" if new_lines else "")
            lbl_p.write_text(content, encoding="utf-8")

    return fixes
