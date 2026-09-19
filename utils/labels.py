def color_title(color) -> str:
    if color.is_default:
        return "Стандарт"
    return color.name
