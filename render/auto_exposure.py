"""第 52 批：从洞穴到雪原时画面先爆白再慢慢变暗、闪烁：测光点..."""

def luminance_linear(r, g, b):
    """按线性亮度权重计算亮度。"""
    raise NotImplementedError("TODO: luminance_linear")

def metering_center(x, y, radius):
    """判断测光点是否落在中心测光区。"""
    raise NotImplementedError("TODO: metering_center")

def adapt_rate(current, target, up_rate, down_rate, dt):
    """按上下行不同速率推进曝光。"""
    raise NotImplementedError("TODO: adapt_rate")

def normalize_time(delta, dt):
    """按帧时间归一化曝光变化量。"""
    raise NotImplementedError("TODO: normalize_time")

def blend_manual(auto, manual, t):
    """在自动与手动曝光之间插值。"""
    raise NotImplementedError("TODO: blend_manual")

def exposure_stops(base, stops):
    """按曝光档数缩放基础曝光。"""
    raise NotImplementedError("TODO: exposure_stops")

def reset_on_cut(prev_camera, curr_camera):
    """判断相机切换是否需要重置曝光历史。"""
    raise NotImplementedError("TODO: reset_on_cut")

def hdr_nonnegative(value):
    """把 HDR 亮度钳制为非负。"""
    raise NotImplementedError("TODO: hdr_nonnegative")
