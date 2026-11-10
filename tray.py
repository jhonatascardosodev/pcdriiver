"""Ícone na bandeja do sistema (opcional)."""
import pystray
from PIL import Image, ImageDraw


def criar(on_open, on_quit):
    img = Image.new("RGB", (64, 64), "#1f3a5f")
    d = ImageDraw.Draw(img)
    d.rectangle((10, 38, 20, 54), fill="#4caf50")
    d.rectangle((26, 24, 36, 54), fill="#ffc107")
    d.rectangle((42, 10, 52, 54), fill="#f44336")
    menu = pystray.Menu(
        pystray.MenuItem("Abrir", lambda icon, item: on_open(), default=True),
        pystray.MenuItem("Sair", lambda icon, item: on_quit()),
    )
    return pystray.Icon("monitorpc", img, "Monitor PC", menu)
