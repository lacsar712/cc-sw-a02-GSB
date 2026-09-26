from decimal import Decimal

DEFAULT_TOLERANCE_NM = 0.08


def judge(nominal: float, measured: float, tolerance_nm: float) -> tuple[str, str]:
    # 十进制精确比较：偏差等于档位也算“不大于”，写合格
    delta = abs(Decimal(str(measured)) - Decimal(str(nominal)))
    tier = Decimal(str(tolerance_nm))
    if delta <= tier:
        return "合格", f"偏差 {delta:.4f} nm 在允差 {tolerance_nm} 内"
    return "超差", f"偏差 {delta:.4f} nm 超过允差 {tolerance_nm}"
