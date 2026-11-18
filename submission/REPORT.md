# Báo cáo Day 09 — Tạ Xuân Anh Vũ, 2A202603173

## 1. Kết luận trước
Pipeline kết luận **HOLD** (mã thoát `10`, không phải Release). Từ lô đầu vào **224 ảnh** (`data/raw`), bước nhận dữ liệu loại **22/224 ảnh** (hỏng, nhỏ, trùng, rò rỉ test), còn **202/224 ảnh** đi vào QC và xuất **bản NHÁP** (`submission/export/clean_v1/`, `manifest.json` ghi `decision: Hold`). Toàn bộ lỗi bắt buộc đã về **0**, nhưng sau ngân sách duyệt **80/125 ảnh** trong hàng đợi vẫn còn **38/202 ảnh (18,81%)** mang cảnh báo chưa qua mắt người (`>= 10%` ngưỡng `warn_ratio_hold`), nên chưa đủ điều kiện phát hành chính thức.

## 2. Lỗi và phân việc
Số liệu trước khi sửa lấy từ `submission/reports/02_error_list_v1.csv` (trên 224 ảnh quét cửa vào và 202 ảnh vào QC):

| Mã lỗi | Mức | Số dòng / ảnh | Ai sửa (máy/người) | Vì sao |
|---|---|---:|---|---|
| `CORRUPT_IMAGE`, `BAD_SIZE` | E | 2 / 2, 3 / 3 | **Máy** (intake) | Quy tắc kỹ thuật rõ ràng: không mở được (`load()`) hoặc cạnh ngắn `< 250px` |
| `DUP_IMAGE_EXACT`, `DUP_IMAGE_NEAR` | E | 8 / 8, 4 / 4 | **Máy** (intake) | Trùng byte (MD5) hoặc trùng gần đúng (`phash <= 10`), loại ngay để tránh lặp dữ liệu |
| `LEAK_TEST` | E | 5 / 5 | **Máy** (intake) | Trùng ảnh trong `data/test` (`test_009, 033, 039, 044, 085`), loại để chống metric đẹp giả |
| `BAD_CLASS_NAME` | E | 2 / 1 (`data.yaml`) | **Máy** (autofix) | Sai tên lớp `'Person'`, `'Bus'` → chuẩn hoá lại đúng `cfg["classes"]` |
| `BAD_FORMAT`, `BAD_CLASS_ID`, `BOX_ZERO`, `DUP_BOX` | E | 3/3, 6/6, 4/4, 7/7 | **Máy** (autofix) | Lỗi cú pháp/hình học xác định (`nan`, thiếu cột, ID `-1/4/7/93`, `w/h=0`, lặp IoU `>0.9`) → `drop_line` có log trong `03_fixes.csv` |
| `BOX_OUT_OF_IMAGE` | E | 8 / 8 | **Máy** (autofix) | Tràn biên `> 0.002` → `clip_box` về `[0, 1]` (xoá nếu mất diện tích) |
| `MISSING_LABEL_FILE` | E | 6 / 6 | **Người** (`needs_label`) | Máy không thể bịa nhãn và không tạo file rỗng (nhầm với ảnh nền); đẩy lên đầu hàng đợi |
| `CLASS_RARE` | W | 4 / `<dataset>` | **Máy** (gián tiếp) | Do các ID lạ `-1, 4, 7, 93` gây ra; tự hết sau khi `autofix` xoá dòng `BAD_CLASS_ID` |
| `EMPTY_LABEL`, `BOX_TINY`, `BOX_HUGE` | W | 12/12, 6/4, 3/3 | **Người** | Cần mắt người phân biệt ảnh nền thật hay thiếu nhãn, vật quá nhỏ/lớn có hợp lệ không |
| `POSSIBLE_WRONG_CLASS`, `POSSIBLE_MISSING`, `POSSIBLE_LOOSE_BOX`, `POSSIBLE_FALSE_POS` | W | 18/18, 53/52, 28/24, 25/24 | **Người** (hàng đợi) | Lỗi ngữ nghĩa do `second_opinion` (yolo26l) nghi ngờ; model vẫn có thể sai nên chỉ cảnh báo |

**Giải thích hàng đợi `05_review_queue.csv` và hiệu quả ngân sách 80 ảnh:** `review_queue.py` cộng điểm theo trọng số (`NEEDS_LABEL=10`, `POSSIBLE_WRONG_CLASS=3`, `POSSIBLE_MISSING=2`, `POSSIBLE_FALSE_POS=2`, `POSSIBLE_LOOSE_BOX=1.5`, nhân thêm `1 + conf`) nên **1 ảnh đa lỗi** (`img_0020`, `11.524` điểm) đứng đầu, tiếp ngay sau là toàn bộ **6/6 ảnh `NEEDS_LABEL`** (`10.0` điểm), rồi tới các ảnh nhiều cảnh báo ngữ nghĩa độ tin cậy cao. Với ngân sách **80/125 ảnh**, người duyệt xử lý trọn **6/6 ảnh thiếu file nhãn** và **94/123 cảnh báo ngữ nghĩa (76,4%)** trên **74/103 ảnh**, bao gồm **18/18 (100%)** `POSSIBLE_WRONG_CLASS`, **51/53 (96,2%)** `POSSIBLE_MISSING`, **13/24** `POSSIBLE_FALSE_POS` và **12/28** `POSSIBLE_LOOSE_BOX`. Sau duyệt, `class_stats.csv` còn 4 lớp sạch (`0: 101`, `1: 574`, `2: 41`, `3: 32` box).

## 3. Calibration (2 ngưỡng)
Chạy `pipeline.calibrate` trên `data/calib/` (39 ảnh có đáp án `MANIFEST.csv`, lưu tại `submission/calibration/calibration_report.md`):

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau trên `calib`) | Lý do (đánh đổi) |
|---|---:|---:|---|---|
| `duplicates.phash_dist` | `2` | `10` | `DUP_IMAGE_NEAR`: `1.00 / 0.50` → `1.00 / 0.67` (`DUP_IMAGE_EXACT` giữ `1.00 / 1.00`) | Vì loại ảnh là hành động xoá tự động, ưu tiên **Precision = 1.00**. Mức `10` bắt thêm các bản đổi sáng/cắt nhẹ (`img_0223`↔`img_0077` dist 6, `img_0186`↔`img_0061` dist 10) và bắt thêm `LEAK_TEST` `img_0101`↔`test_039.jpg` mà không xoá nhầm ảnh tốt. |
| `second_opinion.conf` | `0.25` | `0.6` | `WRONG_CLASS`: `0.56 / 0.83` → `0.62 / 0.83`<br>`MISSING`: `0.50 / 1.00` → `0.57 / 1.00`<br>`LOOSE_BOX`: `0.29 / 0.40` → `0.20 / 0.20` | Nâng `conf` lên `0.6` giúp tăng Precision cho `WRONG_CLASS` (+0.06) và `MISSING` (+0.07), giảm báo động giả tốn ngân sách duyệt 80 ảnh trong khi vẫn giữ Recall `MISSING = 1.00`. Nếu tăng lên `0.7–0.8`, Recall `MISSING` tụt xuống `0.88–0.75` (bỏ sót vật thật). Chấp nhận đánh đổi Recall `LOOSE_BOX` thấp hơn. |

**Điểm calibration có thể đánh lừa (kèm bằng chứng trên `data/raw`):** Trên `data/calib` (chỉ 39 ảnh, không có `LEAK_TEST`), ngưỡng `phash_dist = 16` cho **F1 cao nhất (`0.91`, P=1.00 / R=0.83)**. Tuy nhiên khi kiểm tra trực tiếp trên lô `data/raw` (224 ảnh), `phash_dist = 16` làm `LEAK_TEST` nhảy vọt từ 5 lên **11** và `DUP_IMAGE_NEAR` từ 4 lên **7** — mở ảnh đối chiếu bằng mắt cho thấy các cặp ở `dist = 16` hoàn toàn khác nhau (ví dụ `img_0011` người chơi tennis trên sân xanh bị gộp nhầm với `img_0008` hai người trượt tuyết trên núi tuyết). Nếu tin mù quáng vào F1 cao nhất trên `calib`, pipeline sẽ xoá oan 9 ảnh sạch. Ngoài ra, tập `calib` có ít ca chèn (5–8 ca/mã) nên mỗi ảnh làm P/R nhảy 12–20%, và phân bố nhầm lớp trong `calib` lệch so với lỗi tự nhiên `car/truck/bus` trong `raw`.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Chứng minh cửa chặn hoạt động đúng:** Chạy `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb` (không có người duyệt nên 6 ảnh `MISSING_LABEL_FILE` gồm `img_0031, 0053, 0126, 0135, 0170, 0219` vẫn tồn tại ở QC vòng 3). Kết quả: gate trả về **`REWORK`** với lý do `còn 6 lỗi bắt buộc chưa xử lý`, mã thoát **`20`**, và thư mục `work/exp_nb/clean_v1/` **không được xuất** (`EXPORT_EXISTS=False`).

**(b) Các điểm mù pipeline không bắt được (có bằng chứng thực tế):**
1. **Vật thể nhỏ/xa dưới `min_area_px = 600`:** `second_opinion` bỏ qua mọi dự đoán diện tích `< 600 px²`. Khi soi `work/viz/img_0078.png` (nhóm người đi bộ trước cửa hàng ZEEMAN) và `work/viz/img_0161.png` (người đi bộ cuối hành lang chợ mái vòm), nhiều người nhỏ bị bỏ sót nhãn nhưng pipeline không thể báo `POSSIBLE_MISSING`.
2. **Lỗi ngữ nghĩa khi model lớn (`yolo26l`) cũng bỏ sót hoặc bất đồng với nhãn người:** Trên `work/viz/img_0083.png`, người thứ hai đứng cạnh đàn cừu bị mờ/chồng nên cả nhãn gốc lẫn `yolo26l` không cờ `POSSIBLE_MISSING`; ngược lại, sau khi người đã duyệt, `07_error_list_v3.txt` vẫn ghi 3 ca `POSSIBLE_WRONG_CLASS` (`img_0078`, `img_0083`, `img_0220`: nhãn `truck`, model đoán `car`) cho thấy ranh giới `car ↔ truck` (xe van/pickup) là điểm mù ngữ nghĩa chung của model.
3. **Ảnh trùng biến đổi mạnh (`phash > 10`) và box lỏng nhẹ (`0.50 <= IoU < 0.75`):** Ngay trên `calib`, `phash_dist = 10` vẫn bỏ sót 2/6 ảnh gần trùng biến đổi mạnh (không thể nâng lên `16` do xoá nhầm ảnh sạch), và `iou_loose = 0.5` khiến các box lệch nhẹ (IoU `0.55–0.70`) lọt qua không cảnh báo.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa chạy (đang hoàn tất phần lõi trước khi push lên GitHub và chạy notebook `notebooks/day09_train_compare.ipynb` trên Google Colab T4 GPU với 2 seed cho `raw` và `clean`). Sẽ cập nhật bảng `submission/results/comparison.md` và phân tích độ nhiễu giữa các seed sau khi hoàn thành bước train Colab.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối & điều kiện để thành Release:** Giữ nguyên kết luận **HOLD** (chỉ xuất bản nháp `clean_v1` để thử nghiệm train, **không** phát hành sản phẩm). Để chuyển sang **Release** (`warn_ratio < 10%`, tức `< 20/202` ảnh còn cảnh báo chưa duyệt), cần mở rộng ngân sách người duyệt thêm tối thiểu **19 ảnh nữa** (từ 80 lên **≥ 99 ảnh** trong hàng đợi 125 ảnh, ưu tiên các ca `POSSIBLE_MISSING`, `POSSIBLE_LOOSE_BOX` và `POSSIBLE_FALSE_POS` còn lại ở `07_error_list_v3.txt`) — tuyệt đối **không** kéo `second_opinion.conf > 0.85` để làm rỗng hàng đợi giả.

**(b) Ghi chú sử dụng AI:**
- **Prompt chính:** Cung cấp trực tiếp docstring vào/ra và danh sách test ca biên của từng module (`label_format.py`, `gate.py`, `autofix.py`, `second_opinion.py`), yêu cầu chỉ đọc/ghi trong `ds`, không sửa file khoá SHA-1, không đọc `data/test`/`MANIFEST.csv`, và lấy mọi ngưỡng từ `cfg`.
- **Cách kiểm chứng code AI:** Chạy từng bộ unit test riêng (`pytest tests/test_<module>.py`, đạt 50/50), chạy toàn bộ 79 test gồm `test_pipeline_e2e.py`, kiểm tra trên `data/calib/` (tất cả lỗi cú pháp đạt P/R = 1.00), mở trực tiếp ảnh thật trên `data/raw` bằng `viz_labels.py` và chạy `scripts/check_submission.py`.
- **Một lần AI/kịch bản gặp lỗi và cách xử lý:** Khi kiểm tra nhanh `second_opinion` trực tiếp trên `data/raw` (chưa qua `intake`) để khảo sát ngưỡng `conf`, lệnh gọi nhầm sang `ultralytics` do các ảnh hỏng chưa nằm trong `checker_preds.json` và vướng lỗi quyền đọc `/etc/os-release` trên Windows sandbox; đã sửa cách kiểm chứng bằng chạy qua luồng chuẩn `pipeline.run` (có `intake` lọc ảnh hỏng trước) và đối chiếu bằng bảng `pipeline.calibrate` + soi ảnh trực tiếp.
