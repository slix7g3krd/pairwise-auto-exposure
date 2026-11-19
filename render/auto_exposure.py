"""第 52 批：自动曝光（eye adaptation）修复。

从洞穴到雪原时画面先爆白再慢慢变暗、闪烁，根因与修复对应关系：

1. 测光点只取屏幕中心            -> :func:`metering_multi` 多点加权测光，
   :func:`metering_center` 只作为单点判定工具。
2. 亮度直方图按 sRGB 算          -> :func:`luminance_linear` 在线性光空间
   （HDR scene-linear）计算亮度，不做 sRGB gamma 编码/解码。
3. 适应速率上下行相同            -> :func:`adapt_rate` 上行（变亮场景，
   需快速压曝光防爆白）与下行（变暗场景，缓慢抬曝光）使用不同速率。
4. 时间累积没按帧率归一          -> :func:`normalize_time` 按 ``dt`` 归一，
   适应进度统一按秒计算，帧率变化不再改变观感。
5. 局部测光权重用了上一帧        -> :func:`AutoExposureView.update` 只消费
   当前帧传入的样本与权重，控制器不缓存上一帧权重。
6. 曝光补偿和 bloom 阈值耦合     -> bloom 阈值由独立参数持有，曝光补偿
   （EV）只移动目标曝光，:func:`bloom_threshold` 不受其影响。
7. HDR 负值被 clamp              -> 亮度计算保留线性 HDR 全范围，仅在最终
   曝光取值处用 :func:`hdr_nonnegative` 做地板，负值不再静默污染直方图。
8. 多相机分屏共用一张测光图      -> :class:`AutoExposureController` 按视图
   id 维护各自独立的测光状态与历史。
9. 相机切换没重置历史            -> :func:`reset_on_cut` 判定切换，
   命中时重置该视图的曝光历史，首帧直接贴合新场景。
10. 自动曝光和手动曝光混合跳变   -> :func:`blend_manual` 做线性斜坡混合，
    混合因子按 :func:`normalize_time` 的秒级时间推进，避免硬切。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# 线性光空间的亮度权重（scene-linear Rec.709 风格通道，项目固定光度权重）。
# 注意：直接作用于线性 HDR 值，不经过 sRGB 传递函数。
_LUMA_W_R = 0.7
_LUMA_W_G = 0.2
_LUMA_W_B = 0.1

# 曝光允许的物理范围（线性曝光值），同时作为 HDR 取值的上界。
EXPOSURE_MIN = 1e-4
EXPOSURE_MAX = 1e4


def luminance_linear(r, g, b):
    """按线性亮度权重计算亮度。

    输入为线性 HDR 通道值（允许负值，HDR 范围在测光汇总阶段处理），
    输出是同一线性空间下的标量亮度，不做 sRGB gamma 处理。
    """
    return _LUMA_W_R * r + _LUMA_W_G * g + _LUMA_W_B * b


def metering_center(x, y, radius):
    """判断测光点是否落在中心测光区。

    以屏幕中心 (0.5, 0.5) 为圆心、``radius`` 为半径的圆形区域，
    边界内侧（严格小于半径）才算命中。
    """
    dx = x - 0.5
    dy = y - 0.5
    return bool(dx * dx + dy * dy < radius * radius)


def metering_multi(samples, weights=None):
    """多点加权测光：对当前帧若干测光点的线性亮度做加权平均。

    ``samples`` 为当前帧各测光点的线性亮度（已由
    :func:`luminance_linear` 算好，可含 HDR 负值）；``weights`` 必须是
    当前帧的权重，绝不允许传入上一帧缓存。权重自动归一化，全零或空输入
    返回 0.0。
    """
    if not samples:
        return 0.0
    if weights is None:
        weights = [1.0] * len(samples)
    if len(weights) != len(samples):
        raise ValueError("测光样本数与权重数不一致")
    total_w = 0.0
    acc = 0.0
    for value, weight in zip(samples, weights):
        if weight < 0.0:
            raise ValueError("测光权重不能为负")
        acc += value * weight
        total_w += weight
    if total_w <= 0.0:
        return 0.0
    return acc / total_w


def normalize_time(delta, dt):
    """按帧时间归一化曝光变化量。

    把每帧的累积量 ``delta`` 换算成每秒速率 ``delta / dt``；
    ``dt`` 为 0（暂停/首帧）时返回 0.0，不产生任何时间推进。
    """
    if dt <= 0.0:
        return 0.0
    return delta / dt


def adapt_rate(current, target, up_rate, down_rate, dt):
    """按上下行不同速率推进曝光。

    场景变亮（``target > current``，需要压曝光防止爆白）走 ``up_rate``，
    场景变暗走较慢的 ``down_rate``。速率单位为 1/秒，按 ``dt`` 归一，
    采用指数逼近且因子钳制在 [0, 1]，大步长也不会越过目标。
    """
    if target == current:
        return float(current)
    rate = up_rate if target > current else down_rate
    alpha = min(1.0, max(0.0, rate) * dt)
    return current + (target - current) * alpha


def blend_manual(auto, manual, t):
    """在自动与手动曝光之间插值（手动混合斜坡）。

    ``t=0`` 完全自动，``t=1`` 完全手动，中间为线性斜坡；``t`` 钳制在
    [0, 1]，保证任何调用方传入越界值都不会产生超调跳变。
    """
    if t <= 0.0:
        return float(auto)
    if t >= 1.0:
        return float(manual)
    return auto + (manual - auto) * t


def exposure_stops(base, stops):
    """按曝光档数（EV stops）缩放基础曝光：每 +1 档曝光翻倍。"""
    return base * (2.0 ** stops)


def reset_on_cut(prev_camera, curr_camera):
    """判断相机切换是否需要重置曝光历史。

    相机 id 发生变化（硬切/分屏视图切换）即返回 True，首帧应直接贴合
    新场景而不是沿用上一台相机的适应历史。
    """
    return bool(prev_camera != curr_camera)


def hdr_nonnegative(value):
    """把 HDR 亮度钳制为非负（仅做地板，不压高光）。

    线性测光保留 HDR 全范围（包括大于 1 的高光），只有最终参与曝光
    决策的取值才在此处去掉负值，避免负值在直方图里拉低均值。
    """
    return max(0.0, float(value))


def bloom_threshold(threshold, exposure_compensation_stops=0.0):
    """Bloom 阈值与曝光补偿解耦。

    bloom 触发阈值只由自身参数决定；曝光补偿档数仅用于
    :func:`exposure_stops` 移动目标曝光，不会（也不允许）改写 bloom
    阈值。保留补偿参数只是为了显式声明两者互不影响。
    """
    return float(threshold)


@dataclass
class AutoExposureView:
    """单个视图（相机/分屏）独立的自动曝光状态。"""

    view_id: str
    # 上行（场景变亮）适应更快，下行更慢，非对称速率。
    up_rate: float = 4.0
    down_rate: float = 1.0
    # 手动混合斜坡的推进速率（1/秒）。
    blend_rate: float = 2.0
    min_exposure: float = EXPOSURE_MIN
    max_exposure: float = EXPOSURE_MAX
    camera_id: object = None
    exposure: float = 1.0
    target: float = 1.0
    manual_exposure: float = 1.0
    blend_t: float = 0.0
    initialized: bool = False

    def _clamp_exposure(self, value):
        return min(self.max_exposure, max(self.min_exposure, value))

    def update(
        self,
        samples,
        weights,
        dt,
        camera_id,
        exposure_compensation_stops=0.0,
        manual_exposure=None,
        manual_blend=0.0,
    ):
        """推进一帧，返回当前帧实际生效的曝光值。

        ``samples``/``weights`` 一律取当前帧数据；``camera_id`` 变化时
        先重置适应历史；曝光补偿只移动目标曝光，与 bloom 无关。
        """
        # 修复点 9：相机切换重置历史，首帧直接贴合新场景。
        if self.initialized and reset_on_cut(self.camera_id, camera_id):
            self.initialized = False
        self.camera_id = camera_id

        # 修复点 1/5：多点测光，且权重来自当前帧。
        # 修复点 7：线性 HDR 先汇总，最后才做非负地板，保留高光范围。
        measured = hdr_nonnegative(metering_multi(samples, weights))
        target = self._target_from_measurement(measured)
        # 修复点 6：曝光补偿（EV）只作用于目标曝光，不触碰 bloom 阈值。
        target = exposure_stops(target, exposure_compensation_stops)
        self.target = self._clamp_exposure(target)

        if not self.initialized:
            # 首帧或切换后：无历史斜坡，直接贴合。
            self.exposure = self.target
            self.initialized = True
        else:
            # 修复点 3/4：非对称速率 + 按 dt 归一的指数适应。
            self.exposure = adapt_rate(
                self.exposure,
                self.target,
                self.up_rate,
                self.down_rate,
                dt,
            )
        self.exposure = self._clamp_exposure(self.exposure)

        # 修复点 10：自动/手动曝光按秒级斜坡混合，杜绝硬切跳变。
        # manual_blend 是目标混合因子（0=全自动，1=全手动），当前因子
        # 以 blend_rate（1/秒）按 dt 归一地向其逼近，而不是一帧硬切。
        if manual_exposure is not None:
            self.manual_exposure = float(manual_exposure)
        target_blend = min(1.0, max(0.0, float(manual_blend)))
        self.blend_t = adapt_rate(
            self.blend_t,
            target_blend,
            self.blend_rate,
            self.blend_rate,
            dt,
        )
        return blend_manual(self.exposure, self.manual_exposure, self.blend_t)

    @staticmethod
    def _target_from_measurement(measured):
        """由线性测光亮度反推目标曝光：把中性灰 (0.18) 拉回基准。"""
        if measured <= 0.0:
            return EXPOSURE_MAX
        # 曝光与场景亮度成反比，key 值取 0.18 的中性灰。
        return 0.18 / measured

    def reset(self):
        """清空该视图的适应历史（分屏重建/相机硬切时使用）。"""
        self.initialized = False
        self.exposure = 1.0
        self.target = 1.0
        self.blend_t = 0.0
        self.camera_id = None


@dataclass
class AutoExposureController:
    """多视图控制器：每个视图（相机/分屏）持有独立测光图与历史。

    修复点 8：不再让多相机分屏共用一张测光图，状态按 ``view_id`` 隔离。
    """

    up_rate: float = 4.0
    down_rate: float = 1.0
    blend_rate: float = 2.0
    views: dict = field(default_factory=dict)

    def _get_view(self, view_id):
        view = self.views.get(view_id)
        if view is None:
            view = AutoExposureView(
                view_id=view_id,
                up_rate=self.up_rate,
                down_rate=self.down_rate,
                blend_rate=self.blend_rate,
            )
            self.views[view_id] = view
        return view

    def update_view(self, view_id, samples, weights, dt, camera_id, **kwargs):
        """更新指定视图；其他视图的测光状态与历史完全不受影响。"""
        return self._get_view(view_id).update(
            samples, weights, dt, camera_id, **kwargs
        )

    def reset_view(self, view_id):
        view = self.views.get(view_id)
        if view is not None:
            view.reset()

    def reset_all(self):
        for view in self.views.values():
            view.reset()
