# pairwise-auto-exposure

从洞穴到雪原时画面先爆白再慢慢变暗、闪烁：测光点只取屏幕中心；亮度直方图按 sRGB 算；适应速率上下行相同；时间累积没按帧率归一；局部测光权重用了上一帧；曝光补偿和 bloom 阈值耦合；HDR 负值被 clamp；多相机分屏共用一张测光图；相机切换没重置历史；自动曝光和手动曝光混合跳变。render/auto_exposure.py 是核心，tests/test_auto_exposure.py 15个红。要修的是：多点测光；线性亮度；非对称适应；按 dt 归一；当前帧权重；bloom 解耦；HDR 范围；按视图测光；切换重置；手动混合斜坡。

## 运行

```bash
python -m pytest tests -q
```

初始状态：15 个用例失败。修复实现使全部用例通过，不要修改 `tests/` 下的测试。

子方向：图形渲染；任务类型：Bugfix；语言/框架：Python 3, pytest；环境可复现等级：无外部依赖。
