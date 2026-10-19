"""
FitLearn - Penanda server lokal
Jalankan ini di laptop BARENG uvicorn, supaya gelang bisa nemuin IP laptop sendiri
tanpa perlu ngetik IP di firmware.

Cara pakai (terminal terpisah dari uvicorn):
    python penanda_server.py

Kalau Windows Firewall nanya, izinkan untuk Private networks.
Tidak butuh library tambahan.
"""

import socket

PORT_CARI = 45454  # harus sama dengan PORT_CARI di firmware

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("", PORT_CARI))

print(f"Penanda server FitLearn aktif di port {PORT_CARI}, nunggu gelang nyari...")

while True:
    data, alamat = sock.recvfrom(64)
    if data.startswith(b"FITLEARN_CARI"):
        sock.sendto(b"FITLEARN_SERVER", alamat)
        print(f"Gelang {alamat[0]} nyari server, sudah dibalas.")
