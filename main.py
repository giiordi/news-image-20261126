"""The Meridian Post: a deterministic, hand-drawn one-image newspaper.

Only Python's standard library is used. All glyphs, vector-like raster
primitives, layout, PNG chunks and checksums are authored in this file.
"""
from pathlib import Path
import math
import os
import shutil
import struct
import zlib

WIDTH = HEIGHT = 1024
SAMPLE = 2
INK = '#142F40'
PAPER = '#F5F7F7'
RUST = '#B44830'
MUTED = '#526771'
PALE = '#E1E9EB'
RULE = '#B6C5CB'
WHITE = '#FFFFFF'
GOLD = '#CDA457'

# Each slash separates one of seven rows in our original bitmap alphabet.
GLYPHS = {
 'A':'01110/10001/10001/11111/10001/10001/10001',
 'B':'11110/10001/10001/11110/10001/10001/11110',
 'C':'01111/10000/10000/10000/10000/10000/01111',
 'D':'11110/10001/10001/10001/10001/10001/11110',
 'E':'11111/10000/10000/11110/10000/10000/11111',
 'F':'11111/10000/10000/11110/10000/10000/10000',
 'G':'01111/10000/10000/10111/10001/10001/01111',
 'H':'10001/10001/10001/11111/10001/10001/10001',
 'I':'11111/00100/00100/00100/00100/00100/11111',
 'J':'00111/00010/00010/00010/10010/10010/01100',
 'K':'10001/10010/10100/11000/10100/10010/10001',
 'L':'10000/10000/10000/10000/10000/10000/11111',
 'M':'10001/11011/10101/10101/10001/10001/10001',
 'N':'10001/11001/10101/10011/10001/10001/10001',
 'O':'01110/10001/10001/10001/10001/10001/01110',
 'P':'11110/10001/10001/11110/10000/10000/10000',
 'Q':'01110/10001/10001/10001/10101/10010/01101',
 'R':'11110/10001/10001/11110/10100/10010/10001',
 'S':'01111/10000/10000/01110/00001/00001/11110',
 'T':'11111/00100/00100/00100/00100/00100/00100',
 'U':'10001/10001/10001/10001/10001/10001/01110',
 'V':'10001/10001/10001/10001/10001/01010/00100',
 'W':'10001/10001/10001/10101/10101/11011/10001',
 'X':'10001/10001/01010/00100/01010/10001/10001',
 'Y':'10001/10001/01010/00100/00100/00100/00100',
 'Z':'11111/00001/00010/00100/01000/10000/11111',
 '0':'01110/10001/10011/10101/11001/10001/01110',
 '1':'00100/01100/00100/00100/00100/00100/01110',
 '2':'01110/10001/00001/00010/00100/01000/11111',
 '3':'11110/00001/00001/01110/00001/00001/11110',
 '4':'00010/00110/01010/10010/11111/00010/00010',
 '5':'11111/10000/10000/11110/00001/00001/11110',
 '6':'01110/10000/10000/11110/10001/10001/01110',
 '7':'11111/00001/00010/00100/01000/01000/01000',
 '8':'01110/10001/10001/01110/10001/10001/01110',
 '9':'01110/10001/10001/01111/00001/00001/01110',
 '.':'00000/00000/00000/00000/00000/00110/00110',
 ',':'00000/00000/00000/00000/00110/00100/01000',
 ':':'00000/00110/00110/00000/00110/00110/00000',
 ';':'00000/00110/00110/00000/00110/00100/01000',
 '-':'00000/00000/00000/11111/00000/00000/00000',
 '/':'00001/00010/00010/00100/01000/01000/10000',
 '%':'11001/11010/00010/00100/01000/01011/10011',
 "'":'00100/00100/01000/00000/00000/00000/00000',
 '+':'00000/00100/00100/11111/00100/00100/00000',
 ' ':'00000/00000/00000/00000/00000/00000/00000',
}


def rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


class Canvas:
    """A small supersampled RGB canvas with clipped scanline primitives."""

    def __init__(self):
        self.w = WIDTH * SAMPLE
        self.h = HEIGHT * SAMPLE
        self.pixels = bytearray(bytes(rgb(PAPER)) * (self.w * self.h))
        self.text_boxes = []

    def rect(self, x, y, w, h, color):
        x0, y0 = max(0, round(x * SAMPLE)), max(0, round(y * SAMPLE))
        x1 = min(self.w, round((x + w) * SAMPLE))
        y1 = min(self.h, round((y + h) * SAMPLE))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(rgb(color)) * (x1 - x0)
        for yy in range(y0, y1):
            offset = (yy * self.w + x0) * 3
            self.pixels[offset:offset + len(row)] = row

    def polygon(self, points, color):
        points = [(x * SAMPLE, y * SAMPLE) for x, y in points]
        lower = max(0, math.floor(min(y for x, y in points)))
        upper = min(self.h, math.ceil(max(y for x, y in points)))
        for yy in range(lower, upper):
            scan = yy + 0.5
            crosses = []
            for a, b in zip(points, points[1:] + points[:1]):
                if (a[1] <= scan < b[1]) or (b[1] <= scan < a[1]):
                    crosses.append(a[0] + (scan - a[1]) *
                                   (b[0] - a[0]) / (b[1] - a[1]))
            crosses.sort()
            for left, right in zip(crosses[::2], crosses[1::2]):
                self.rect(left / SAMPLE, yy / SAMPLE,
                          (right - left) / SAMPLE, 1 / SAMPLE, color)

    def line(self, x1, y1, x2, y2, color, thickness=2):
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if not length:
            return
        nx, ny = -dy / length * thickness / 2, dx / length * thickness / 2
        self.polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny),
                      (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], color)

    def circle(self, x, y, radius, color):
        self.polygon([(x + math.cos(t * math.tau / 64) * radius,
                       y + math.sin(t * math.tau / 64) * radius)
                      for t in range(64)], color)

    @staticmethod
    def measure(value, size):
        return (len(value) * 6 - 1) * size if value else 0

    def text(self, value, x, y, size=2, color=INK, align='left', limit=None):
        value = value.upper()
        width = self.measure(value, size)
        if limit is not None and width > limit:
            raise ValueError(f'Text exceeds its column: {value!r} ({width}>{limit})')
        if align == 'center':
            x -= width / 2
        elif align == 'right':
            x -= width
        if x < 0 or y < 0 or x + width > WIDTH or y + size * 7 > HEIGHT:
            raise ValueError(f'Text outside canvas: {value!r}')
        self.text_boxes.append((value, x, y, x + width, y + size * 7))
        for index, letter in enumerate(value):
            glyph = GLYPHS[letter].split('/')
            for row, cells in enumerate(glyph):
                for col, bit in enumerate(cells):
                    if bit == '1':
                        self.rect(x + (index * 6 + col) * size,
                                  y + row * size, size, size, color)

    def lines(self, values, x, y, size=2, leading=22, color=INK, limit=None):
        for i, value in enumerate(values):
            self.text(value, x, y + i * leading, size, color, limit=limit)

    def raw_rgb(self):
        out = bytearray(WIDTH * HEIGHT * 3)
        for y in range(HEIGHT):
            for x in range(WIDTH):
                dest = (y * WIDTH + x) * 3
                origin = ((y * 2) * self.w + x * 2) * 3
                for c in range(3):
                    out[dest + c] = (self.pixels[origin + c] +
                                     self.pixels[origin + 3 + c] +
                                     self.pixels[origin + self.w * 3 + c] +
                                     self.pixels[origin + self.w * 3 + 3 + c]) // 4
        return out


def png_bytes(width, height, pixels):
    """Encode deterministic RGB PNG data without external imaging libraries."""
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload +
                struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))
    rows = b''.join(b'\x00' + pixels[y * width * 3:(y + 1) * width * 3]
                    for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))


def draw_sudan(c):
    c.rect(32, 188, 960, 236, INK)
    c.text('01 / SUDAN', 54, 207, 2.7, '#F0AD89')
    c.lines(['DRONE STRIKES', 'KILL 19 CIVILIANS'], 54, 246,
            5.2, 48, WHITE, 570)
    c.lines(['BLUE NILE STATE, SUDAN.',
             'CIVILIAN DEATHS REPORTED AFTER ATTACKS.'],
            54, 359, 2.2, 25, '#DAE4E8', 570)
    # A geographically suggestive Sudan silhouette and Blue Nile locator.
    c.polygon([(734, 215), (864, 215), (874, 249), (901, 270),
               (886, 299), (869, 309), (861, 345), (836, 367),
               (815, 357), (803, 373), (782, 361), (761, 335),
               (741, 330), (724, 300), (713, 273), (725, 254)], '#607987')
    c.line(818, 238, 818, 292, '#B8D5E2', 3)
    c.line(818, 292, 846, 333, '#B8D5E2', 3)
    c.circle(846, 333, 12, '#F0AD89')
    c.circle(846, 333, 5, RUST)
    c.line(857, 334, 941, 334, '#F0AD89', 2)
    c.text('BLUE NILE', 956, 386, 2.1, WHITE, 'right')
    c.text('SUDAN', 743, 241, 2.1, WHITE)


def draw_gaza(c):
    x = 32
    c.text('02 / GAZA', x, 453, 2.3, RUST)
    c.lines(['AIRSTRIKE KILLS', 'HAMAS OFFICIAL'], x, 489, 3.1, 30, INK, 298)
    c.lines(['ISRAELI STRIKE KILLS', 'A SENIOR HAMAS OFFICIAL',
             'AND HIS FAMILY IN GAZA.'], x, 560, 2.1, 23, INK, 298)
    # A quiet, schematic skyline rather than a graphic depiction of victims.
    base = 696
    for bx, by, bw in [(32, 662, 38), (76, 642, 45), (129, 658, 28),
                       (168, 637, 42), (222, 663, 32), (265, 646, 55)]:
        c.rect(bx, by, bw, base - by, PALE)
        c.rect(bx + 7, by + 9, 6, 8, '#97ADB7')
        c.rect(bx + 21, by + 9, 6, 8, '#97ADB7')
    c.line(32, base, 330, base, INK, 2)
    c.polygon([(152, 663), (168, 682), (181, 672), (197, 696),
               (145, 696)], MUTED)
    c.line(32, 720, 330, 720, RULE, 1)


def draw_indonesia(c):
    x = 32
    c.text('05 / INDONESIA', x, 742, 2.3, RUST)
    c.lines(['NINE MINERS', 'DIE IN FLOOD'], x, 779, 3.4, 32, INK, 298)
    c.lines(['GOLD MINE FLOODS', 'IN INDONESIA;', 'NINE MINERS KILLED.'],
            x, 859, 2.2, 24, INK, 298)
    c.polygon([(261, 949), (289, 906), (326, 949)], MUTED)
    c.polygon([(276, 949), (291, 925), (309, 949)], INK)
    c.line(252, 953, 332, 953, '#4C8DA7', 4)
    c.line(268, 962, 332, 962, '#4C8DA7', 3)


def draw_ukraine(c):
    x = 363
    c.text('03 / UKRAINE', x, 453, 2.3, RUST)
    c.lines(['ENERGY SITES', 'UNDER FIRE'], x, 489, 3.5, 34, INK, 296)
    c.lines(['RUSSIA-UKRAINE', 'ESCALATION: STRIKES', 'HIT ENERGY SITES.'],
            x, 575, 2.25, 25, INK, 296)
    # Energy infrastructure above a shipping silhouette links both fronts.
    c.rect(x, 670, 296, 160, PALE)
    c.line(412, 688, 389, 806, MUTED, 3)
    c.line(412, 688, 435, 806, MUTED, 3)
    for yy, half in [(714, 26), (738, 32), (766, 38)]:
        c.line(412 - half, yy, 412 + half, yy, MUTED, 3)
    c.line(396, 763, 430, 715, MUTED, 2)
    c.line(395, 716, 432, 766, MUTED, 2)
    c.line(384, 714, 363, 729, MUTED, 1)
    c.line(442, 714, 488, 740, MUTED, 1)
    c.polygon([(533, 679), (512, 719), (531, 719),
               (519, 754), (559, 704), (538, 704)], GOLD)
    c.polygon([(472, 780), (632, 780), (614, 807), (489, 807)], INK)
    c.rect(508, 759, 93, 18, MUTED)
    for bx in (511, 542, 573):
        c.rect(bx, 762, 25, 13, '#8CA7B4')
    c.rect(599, 742, 24, 35, WHITE)
    c.rect(603, 748, 17, 7, INK)
    c.line(465, 814, 638, 814, '#4C8DA7', 3)
    c.line(479, 821, 626, 821, '#4C8DA7', 2)
    c.lines(['UKRAINE HITS RUSSIAN', 'CARGO SHIP IN THE', 'GULF OF FINLAND.'],
            x, 857, 2.2, 25, INK, 296)
    c.text('LAND / SEA / ENERGY', x, 951, 1.9, MUTED)


def draw_markets(c):
    x = 695
    c.text('04 / US + MARKETS', x, 453, 2.3, RUST)
    c.lines(['TARIFF THREAT', 'STOCKS SLIDE'], x, 489, 3.45, 34, INK, 297)
    c.lines(['TRUMP WEIGHS NEW TARIFFS', 'ON CHINA, JAPAN AND EU.'],
            x, 575, 2.05, 23, INK, 297)
    c.rect(x, 638, 297, 59, '#EEE7E2')
    c.text('NASDAQ', x + 12, 651, 1.8, MUTED)
    c.text('-1.5%', x + 12, 673, 2.4, RUST)
    c.text('NVIDIA', x + 162, 651, 1.8, MUTED)
    c.text('-6%', x + 162, 673, 2.4, RUST)
    c.text('TUESDAY SESSION', x, 707, 1.3, MUTED)
    c.line(x, 733, 992, 733, RULE, 1)


def draw_colombia(c):
    x = 695
    c.text('06 / COLOMBIA', x, 753, 2.3, RUST)
    c.lines(['25 HOSTAGES', 'IN CARTAGENA'], x, 790, 3.45, 33, INK, 297)
    c.lines(['GUNMEN TAKE 25 HOSTAGES', 'AT A SUPERMARKET IN', 'CARTAGENA, COLOMBIA.'],
            x, 872, 2.15, 24, INK, 297)
    c.rect(924, 954, 68, 15, INK)
    for bx in range(924, 992, 12):
        c.rect(bx, 949, 6, 7, RUST)
    c.rect(945, 958, 12, 11, WHITE)


def render():
    c = Canvas()
    c.text('WORLD EDITION', 32, 22, 1.8, MUTED)
    c.text('SIX STORIES / ONE DAY', 992, 22, 1.8, MUTED, 'right')
    c.text('THE MERIDIAN POST', 512, 57, 8, INK, 'center')
    c.text('THURSDAY 26 NOVEMBER 2026', 512, 133, 3.3, RUST, 'center')
    c.rect(32, 169, 960, 4, RUST)
    draw_sudan(c)
    c.line(346, 449, 346, 969, RULE, 1)
    c.line(678, 449, 678, 969, RULE, 1)
    draw_gaza(c)
    draw_indonesia(c)
    draw_ukraine(c)
    draw_markets(c)
    draw_colombia(c)
    c.line(32, 986, 992, 986, INK, 2)
    c.text('26 NOV 2026', 32, 999, 1.65, MUTED)
    c.text('THE WORLD, IN ONE FRAME', 992, 999, 1.65, MUTED, 'right')
    # Text bounding boxes catch accidental intersections during every render.
    for i, (a, ax, ay, ar, ab) in enumerate(c.text_boxes):
        for b, bx, by, br, bb in c.text_boxes[i + 1:]:
            if ax < br and bx < ar and ay < bb and by < ab:
                raise ValueError(f'Text overlap: {a!r} / {b!r}')
    return png_bytes(WIDTH, HEIGHT, c.raw_rgb())


def main():
    output = Path(os.environ.get('MAKEFUN_OUTPUT_DIR', '/output'))
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'entry.png'
    committed = Path(__file__).resolve().with_name('entry.png')
    if committed.is_file():
        if committed.resolve() != target.resolve():
            shutil.copyfile(committed, target)
    else:
        target.write_bytes(render())


if __name__ == '__main__':
    main()
