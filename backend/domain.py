def judge(nominal: float, measured: float, tolerance_nm: float) -> tuple[str, str]:
    delta = abs(measured - nominal)
    if delta <= tolerance_nm:
        return "合格", f"偏差 {delta:.4f} nm 在允差 {tolerance_nm} nm 内"
    return "超差", f"偏差 {delta:.4f} nm 超过允差 {tolerance_nm} nm"
