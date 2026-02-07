"""Расчёт сегмента гостя по visits_count и порогам из настроек.

Логика:
- Новичок: 0 визитов
- Постоянный: visits >= regular_threshold и < vip_threshold
- VIP: visits >= vip_threshold
"""


def calc_segment(
    visits_count: int,
    regular_threshold: int,
    vip_threshold: int,
) -> str:
    """Вычислить сегмент по количеству визитов и порогам.

    Args:
        visits_count: количество визитов гостя
        regular_threshold: порог для статуса «Постоянный»
        vip_threshold: порог для статуса «VIP» (должен быть >= regular_threshold)

    Returns:
        "Новичок" | "Постоянный" | "VIP"
    """
    if vip_threshold <= regular_threshold:
        vip_threshold = regular_threshold + 1
    if visits_count >= vip_threshold:
        return "VIP"
    if visits_count >= regular_threshold:
        return "Постоянный"
    return "Новичок"
