from pipeline.checks import aspect_ratio


def find(issues, code="BOX_EXTREME_AR"):
    return [(i.image, i.line) for i in issues if i.code == code]


def run(make_ds, cfg, lines, size=(640, 480)):
    ds = make_ds(images={"a": 1}, labels={"a": lines}, size=size)
    return aspect_ratio.run(ds, cfg)


def test_normal_boxes_are_silent(make_ds, cfg):
    assert run(make_ds, cfg, ["0 0.5 0.5 0.2 0.2", "1 0.3 0.5 0.1 0.3"]) == []


def test_very_thin_vertical_box_flagged(make_ds, cfg):
    # w_px = 0.01 * 640 = 6.4, h_px = 0.4 * 480 = 192 -> AR = 30.0 > 6.0
    iss = run(make_ds, cfg, ["1 0.5 0.5 0.01 0.4"], size=(640, 480))
    assert find(iss) == [("a", 1)]
    assert iss[0].severity == "warn" and iss[0].extra["aspect_ratio"] == 30.0


def test_very_wide_horizontal_box_flagged(make_ds, cfg):
    # w_px = 0.5 * 640 = 320, h_px = 0.05 * 480 = 24 -> AR = 13.33 > 6.0
    iss = run(make_ds, cfg, ["0 0.5 0.5 0.5 0.05"], size=(640, 480))
    assert find(iss) == [("a", 1)]
    assert iss[0].extra["aspect_ratio"] > 13.0


def test_non_square_image_uses_pixel_aspect_ratio(make_ds, cfg):
    # Trên ảnh 1000x100, box w=0.2, h=0.2 có pixel 200x20 -> AR thật = 10:1 (> 6.0)
    iss = run(make_ds, cfg, ["0 0.5 0.5 0.2 0.2"], size=(1000, 100))
    assert find(iss) == [("a", 1)]
    assert iss[0].extra["aspect_ratio"] == 10.0


def test_threshold_comes_from_config(make_ds, cfg):
    # w_px = 0.2 * 500 = 100, h_px = 0.05 * 500 = 25 -> AR = 4.0
    assert run(make_ds, cfg, ["0 0.5 0.5 0.2 0.05"], size=(500, 500)) == []
    cfg["aspect_ratio"] = {"max_ratio": 3.0}
    assert find(run(make_ds, cfg, ["0 0.5 0.5 0.2 0.05"], size=(500, 500))) == [("a", 1)]


def test_blank_lines_keep_original_line_numbers(make_ds, cfg):
    iss = run(make_ds, cfg, ["0 0.5 0.5 0.2 0.2", "", "1 0.5 0.5 0.01 0.4"], size=(640, 480))
    assert find(iss) == [("a", 3)]


def test_bad_lines_and_zero_box_do_not_crash(make_ds, cfg):
    lines = ["garbage", "93 0.5 0.5 0.01 0.4", "1 0.5 0.5 0 0.4", "1 0.5 0.5 0.2 0", "1 0.5 0.5 0.01 0.4"]
    iss = run(make_ds, cfg, lines, size=(640, 480))
    assert find(iss) == [("a", 5)]
