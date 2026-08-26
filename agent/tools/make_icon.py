#!/usr/bin/env python3
"""Sinh agent.ico (classic BMP icon 32x32, 32bpp) — không cần PIL."""
import struct, zlib, os, sys

W = H = 32

def make_pixels():
    # nền xanh dương nhạt; màn hình máy tính trắng có viền xanh đậm
    px = [[(0, 0, 0, 0)] * W for _ in range(H)]  # transparent
    bg = (0x2B, 0x6B, 0xC9, 0xFF)
    frame = (0x14, 0x3E, 0x7A, 0xFF)
    screen = (0xE8, 0xF1, 0xFD, 0xFF)
    stand = (0x14, 0x3E, 0x7A, 0xFF)
    for y in range(H):
        for x in range(W):
            px[y][x] = bg
    # màn hình: khung từ (4,3) đến (27,21), màn từ (6,5) đến (25,19)
    for y in range(3, 22):
        for x in range(4, 28):
            px[y][x] = frame
    for y in range(5, 20):
        for x in range(6, 26):
            px[y][x] = screen
    # chân đế
    for y in range(22, 25):
        for x in range(12, 20):
            px[y][x] = stand
    for y in range(24, 26):
        for x in range(8, 24):
            px[y][x] = stand
    return px

def bmp_data(px):
    # BITMAPINFOHEADER + XOR (bottom-up BGRA) + AND mask (opaque)
    header = struct.pack('<IiiHHIIiiII', 40, W, H * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    xor = b''
    for y in range(H - 1, -1, -1):  # bottom-up
        for x in range(W):
            r, g, b, a = px[y][x]
            xor += struct.pack('<BBBB', b, g, r, a)
    and_mask = b'\x00' * (H * ((W + 31) // 32) * 4)  # all opaque
    return header + xor + and_mask

def main(out):
    px = make_pixels()
    data = bmp_data(px)
    # ICONDIR
    ico = struct.pack('<HHH', 0, 1, 1)
    ico += struct.pack('<BBBBHHII', W, H, 0, 0, 1, 32, len(data), 22)
    ico += data
    with open(out, 'wb') as f:
        f.write(ico)
    print(f"wrote {out} ({len(ico)} bytes)")

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'agent.ico')
