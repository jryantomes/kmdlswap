# SPDX-License-Identifier: GPL-3.0-or-later
"""Jade Empire PC texture binary (``.txb``) reader, decoder, and encoder.

The PC resources use a 128-byte header followed by one or more mip levels and
an optional text TXI tail.  Retail files in the supplied corpus use raw BGRA,
raw grayscale, DXT1, or DXT5.  The reader validates the complete declared mip
chain and decodes the highest-resolution level to RGBA8 for Blender.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

from .binary import BinaryView

TXB_HEADER_SIZE = 128
TXB_ENCODING_BGRA = 0x04
TXB_ENCODING_GRAYSCALE = 0x09
TXB_ENCODING_DXT1 = 0x0A
TXB_ENCODING_DXT5 = 0x0C
TXB_MAX_MIP_COUNT = 32
TXB_MAX_DECODED_PIXELS = 64 * 1024 * 1024

TXB_ENCODING_NAMES = {
    TXB_ENCODING_BGRA: "BGRA",
    TXB_ENCODING_GRAYSCALE: "grayscale",
    TXB_ENCODING_DXT1: "DXT1",
    TXB_ENCODING_DXT5: "DXT5",
}


@dataclass(frozen=True)
class JadeTextureMip:
    level: int
    width: int
    height: int
    offset: int
    size: int


@dataclass(frozen=True)
class JadeTexture:
    source_path: str
    width: int
    height: int
    encoding: int
    mip_count: int
    declared_data_size: int
    calculated_mip_size: int
    payload_padding_size: int
    payload_padding: bytes
    flags: int
    unknown_float_1: float
    unknown_float_2: float
    mipmaps: tuple[JadeTextureMip, ...]
    rgba: bytes
    txi: str = ""

    @property
    def encoding_name(self) -> str:
        return TXB_ENCODING_NAMES.get(self.encoding, f"unknown_0x{self.encoding:02X}")


# ---------------------------------------------------------------------------
# Header and layout helpers


def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def _mip_level_size(width: int, height: int, encoding: int) -> int:
    if encoding == TXB_ENCODING_BGRA:
        return width * height * 4
    if encoding == TXB_ENCODING_GRAYSCALE:
        return width * height

    blocks_x = max(1, (width + 3) // 4)
    blocks_y = max(1, (height + 3) // 4)
    if encoding == TXB_ENCODING_DXT1:
        return blocks_x * blocks_y * 8
    if encoding == TXB_ENCODING_DXT5:
        return blocks_x * blocks_y * 16
    raise ValueError(f"Unsupported Jade TXB encoding 0x{encoding:02X}")


def _mip_layout(
    width: int,
    height: int,
    encoding: int,
    mip_count: int,
) -> tuple[JadeTextureMip, ...]:
    levels: list[JadeTextureMip] = []
    offset = TXB_HEADER_SIZE
    level_width = width
    level_height = height
    for level in range(mip_count):
        size = _mip_level_size(level_width, level_height, encoding)
        levels.append(
            JadeTextureMip(
                level=level,
                width=level_width,
                height=level_height,
                offset=offset,
                size=size,
            )
        )
        offset += size
        level_width = max(1, level_width >> 1)
        level_height = max(1, level_height >> 1)
    return tuple(levels)


# ---------------------------------------------------------------------------
# Raw texture de-swizzling


def _interleaved_offset(x: int, y: int, width: int, height: int) -> int:
    """Return the source pixel index used by Jade's Morton-style layout.

    This mirrors the bit-interleaving routine used by the xoreos Jade TXB
    loader.  Its integer logarithm is floor(log2(n)).
    """

    width_bits = width.bit_length() - 1
    height_bits = height.bit_length() - 1
    offset = 0
    shift = 0
    while width_bits or height_bits:
        if width_bits:
            offset |= (x & 1) << shift
            x >>= 1
            shift += 1
            width_bits -= 1
        if height_bits:
            offset |= (y & 1) << shift
            y >>= 1
            shift += 1
            height_bits -= 1
    return offset


def _deswizzle_surface(raw: bytes, width: int, height: int, bytes_per_pixel: int) -> bytes:
    expected = width * height * bytes_per_pixel
    if len(raw) < expected:
        raise ValueError(
            f"Swizzled texture level is truncated: expected {expected} bytes, got {len(raw)}"
        )
    out = bytearray(expected)
    for y in range(height):
        for x in range(width):
            source_pixel = _interleaved_offset(x, y, width, height)
            source = source_pixel * bytes_per_pixel
            target = (y * width + x) * bytes_per_pixel
            if source + bytes_per_pixel > expected:
                raise ValueError(
                    f"Swizzle offset {source_pixel} lies outside {width}x{height} surface"
                )
            out[target : target + bytes_per_pixel] = raw[
                source : source + bytes_per_pixel
            ]
    return bytes(out)


def _deswizzle_raw(raw: bytes, width: int, height: int, bytes_per_pixel: int) -> bytes:
    """De-swizzle a raw TXB level.

    Jade's 64x384 BGRA resources are six 64x64 cube faces stacked vertically
    (their TXI tail contains ``cube 1``).  De-swizzling each face separately
    avoids treating the six-face atlas as one non-power-of-two surface.
    """

    expected = width * height * bytes_per_pixel
    if len(raw) < expected:
        raise ValueError(
            f"Raw texture level is truncated: expected {expected} bytes, got {len(raw)}"
        )
    raw = raw[:expected]
    if not _is_power_of_two(width):
        return raw

    if height == width * 6:
        face_size = width * width * bytes_per_pixel
        return b"".join(
            _deswizzle_surface(
                raw[face * face_size : (face + 1) * face_size],
                width,
                width,
                bytes_per_pixel,
            )
            for face in range(6)
        )

    return _deswizzle_surface(raw, width, height, bytes_per_pixel)


# ---------------------------------------------------------------------------
# DXT/S3TC expansion and deterministic block compression


def _expand_565(value: int) -> tuple[int, int, int]:
    red = (value >> 11) & 0x1F
    green = (value >> 5) & 0x3F
    blue = value & 0x1F
    return (
        (red << 3) | (red >> 2),
        (green << 2) | (green >> 4),
        (blue << 3) | (blue >> 2),
    )


def _lerp_channel(
    a: int,
    b: int,
    numerator_a: int,
    numerator_b: int,
    denominator: int,
) -> int:
    return (numerator_a * a + numerator_b * b) // denominator


def _dxt_color_palette(
    color0: int,
    color1: int,
    *,
    force_four_color: bool,
) -> list[tuple[int, int, int, int]]:
    red0, green0, blue0 = _expand_565(color0)
    red1, green1, blue1 = _expand_565(color1)
    palette = [(red0, green0, blue0, 255), (red1, green1, blue1, 255)]
    if color0 > color1 or force_four_color:
        palette.extend(
            [
                (
                    _lerp_channel(red0, red1, 2, 1, 3),
                    _lerp_channel(green0, green1, 2, 1, 3),
                    _lerp_channel(blue0, blue1, 2, 1, 3),
                    255,
                ),
                (
                    _lerp_channel(red0, red1, 1, 2, 3),
                    _lerp_channel(green0, green1, 1, 2, 3),
                    _lerp_channel(blue0, blue1, 1, 2, 3),
                    255,
                ),
            ]
        )
    else:
        palette.extend(
            [
                (
                    (red0 + red1) // 2,
                    (green0 + green1) // 2,
                    (blue0 + blue1) // 2,
                    255,
                ),
                (0, 0, 0, 0),
            ]
        )
    return palette


def _write_block_pixel(
    out: bytearray,
    width: int,
    height: int,
    block_x: int,
    block_y: int,
    pixel_index: int,
    color: tuple[int, int, int, int],
) -> None:
    x = block_x * 4 + (pixel_index & 3)
    y = block_y * 4 + (pixel_index >> 2)
    if x >= width or y >= height:
        return
    target = (y * width + x) * 4
    out[target : target + 4] = bytes(color)


def _decode_dxt1(raw: bytes, width: int, height: int) -> bytes:
    blocks_x = max(1, (width + 3) // 4)
    blocks_y = max(1, (height + 3) // 4)
    expected = blocks_x * blocks_y * 8
    if len(raw) < expected:
        raise ValueError(f"DXT1 level is truncated: expected {expected} bytes, got {len(raw)}")

    out = bytearray(width * height * 4)
    cursor = 0
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            color0, color1, indices = struct.unpack_from("<HHI", raw, cursor)
            cursor += 8
            palette = _dxt_color_palette(color0, color1, force_four_color=False)
            for pixel in range(16):
                _write_block_pixel(
                    out,
                    width,
                    height,
                    block_x,
                    block_y,
                    pixel,
                    palette[(indices >> (2 * pixel)) & 0x03],
                )
    return bytes(out)


def _dxt5_alpha_palette(alpha0: int, alpha1: int) -> list[int]:
    if alpha0 > alpha1:
        return [
            alpha0,
            alpha1,
            (6 * alpha0 + alpha1) // 7,
            (5 * alpha0 + 2 * alpha1) // 7,
            (4 * alpha0 + 3 * alpha1) // 7,
            (3 * alpha0 + 4 * alpha1) // 7,
            (2 * alpha0 + 5 * alpha1) // 7,
            (alpha0 + 6 * alpha1) // 7,
        ]
    return [
        alpha0,
        alpha1,
        (4 * alpha0 + alpha1) // 5,
        (3 * alpha0 + 2 * alpha1) // 5,
        (2 * alpha0 + 3 * alpha1) // 5,
        (alpha0 + 4 * alpha1) // 5,
        0,
        255,
    ]


def _decode_dxt5(raw: bytes, width: int, height: int) -> bytes:
    blocks_x = max(1, (width + 3) // 4)
    blocks_y = max(1, (height + 3) // 4)
    expected = blocks_x * blocks_y * 16
    if len(raw) < expected:
        raise ValueError(f"DXT5 level is truncated: expected {expected} bytes, got {len(raw)}")

    out = bytearray(width * height * 4)
    cursor = 0
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            alpha0 = raw[cursor]
            alpha1 = raw[cursor + 1]
            alpha_indices = int.from_bytes(raw[cursor + 2 : cursor + 8], "little")
            color0, color1, color_indices = struct.unpack_from("<HHI", raw, cursor + 8)
            cursor += 16
            alpha_palette = _dxt5_alpha_palette(alpha0, alpha1)
            color_palette = _dxt_color_palette(color0, color1, force_four_color=True)
            for pixel in range(16):
                red, green, blue, _ = color_palette[
                    (color_indices >> (2 * pixel)) & 0x03
                ]
                alpha = alpha_palette[(alpha_indices >> (3 * pixel)) & 0x07]
                _write_block_pixel(
                    out,
                    width,
                    height,
                    block_x,
                    block_y,
                    pixel,
                    (red, green, blue, alpha),
                )
    return bytes(out)


def _pack_565(red: int, green: int, blue: int) -> int:
    """Quantize an RGB8 colour to an RGB565 endpoint."""

    red5 = max(0, min(31, int(round(int(red) * 31.0 / 255.0))))
    green6 = max(0, min(63, int(round(int(green) * 63.0 / 255.0))))
    blue5 = max(0, min(31, int(round(int(blue) * 31.0 / 255.0))))
    return (red5 << 11) | (green6 << 5) | blue5


def _block_pixels(
    rgba: bytes,
    width: int,
    height: int,
    block_x: int,
    block_y: int,
) -> list[tuple[int, int, int, int]]:
    """Return a complete 4x4 block, extending edge texels when necessary."""

    pixels: list[tuple[int, int, int, int]] = []
    for local_y in range(4):
        y = min(height - 1, block_y * 4 + local_y)
        for local_x in range(4):
            x = min(width - 1, block_x * 4 + local_x)
            offset = (y * width + x) * 4
            pixels.append(tuple(rgba[offset : offset + 4]))  # type: ignore[arg-type]
    return pixels


def _principal_axis_endpoints(
    pixels: list[tuple[int, int, int, int]],
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Choose colour endpoints using a small deterministic PCA fit.

    This is deliberately self-contained rather than depending on a platform
    codec.  It is not an exhaustive cluster fit, but it produces materially
    better endpoints than independent RGB minima/maxima while keeping edited
    TXB export deterministic on every supported host.
    """

    if not pixels:
        return (0, 0, 0), (0, 0, 0)
    count = float(len(pixels))
    mean = tuple(sum(pixel[channel] for pixel in pixels) / count for channel in range(3))
    covariance = [[0.0, 0.0, 0.0] for _ in range(3)]
    for pixel in pixels:
        delta = [pixel[channel] - mean[channel] for channel in range(3)]
        for row in range(3):
            for column in range(3):
                covariance[row][column] += delta[row] * delta[column]

    # Start with a luma-like direction. Four power iterations are sufficient
    # for a 3x3 covariance matrix and avoid any external numeric dependency.
    axis = [0.299, 0.587, 0.114]
    for _ in range(4):
        next_axis = [
            sum(covariance[row][column] * axis[column] for column in range(3))
            for row in range(3)
        ]
        length = sum(component * component for component in next_axis) ** 0.5
        if length <= 1.0e-12:
            break
        axis = [component / length for component in next_axis]

    projections = [
        sum((pixel[channel] - mean[channel]) * axis[channel] for channel in range(3))
        for pixel in pixels
    ]
    minimum = pixels[min(range(len(pixels)), key=projections.__getitem__)][:3]
    maximum = pixels[max(range(len(pixels)), key=projections.__getitem__)][:3]
    return tuple(int(value) for value in maximum), tuple(int(value) for value in minimum)


def _color_error(
    pixels: list[tuple[int, int, int, int]],
    color0: int,
    color1: int,
    *,
    transparent_mode: bool,
    force_four_color: bool,
) -> tuple[int, int]:
    palette = _dxt_color_palette(color0, color1, force_four_color=force_four_color)
    indices = 0
    error = 0
    opaque_limit = 3 if transparent_mode else 4
    for pixel_index, pixel in enumerate(pixels):
        if transparent_mode and pixel[3] < 128:
            selected = 3
        else:
            selected = min(
                range(opaque_limit),
                key=lambda index: (
                    (int(pixel[0]) - palette[index][0]) ** 2
                    + (int(pixel[1]) - palette[index][1]) ** 2
                    + (int(pixel[2]) - palette[index][2]) ** 2
                ),
            )
            candidate = palette[selected]
            error += (
                (int(pixel[0]) - candidate[0]) ** 2
                + (int(pixel[1]) - candidate[1]) ** 2
                + (int(pixel[2]) - candidate[2]) ** 2
            )
        indices |= int(selected) << (2 * pixel_index)
    return error, indices


def _ordered_565_pair(color0: int, color1: int, *, transparent_mode: bool) -> tuple[int, int]:
    if transparent_mode:
        if color0 > color1:
            color0, color1 = color1, color0
    else:
        if color0 < color1:
            color0, color1 = color1, color0
        if color0 == color1:
            if color0 < 0xFFFF:
                color0 += 1
            elif color1 > 0:
                color1 -= 1
    return color0, color1


def _encode_color_block(
    pixels: list[tuple[int, int, int, int]],
    *,
    transparent_mode: bool,
    force_four_color: bool,
) -> bytes:
    fit_pixels = [pixel for pixel in pixels if not transparent_mode or pixel[3] >= 128]
    if not fit_pixels:
        # In DXT1 transparent mode, index 3 is transparent even when endpoints
        # are equal. This canonical all-transparent block is deterministic.
        return struct.pack("<HHI", 0, 0, 0xFFFFFFFF)

    maximum, minimum = _principal_axis_endpoints(fit_pixels)
    bbox_max = tuple(max(pixel[channel] for pixel in fit_pixels) for channel in range(3))
    bbox_min = tuple(min(pixel[channel] for pixel in fit_pixels) for channel in range(3))
    luma_sorted = sorted(
        fit_pixels,
        key=lambda pixel: 299 * pixel[0] + 587 * pixel[1] + 114 * pixel[2],
    )
    luma_max = tuple(int(value) for value in luma_sorted[-1][:3])
    luma_min = tuple(int(value) for value in luma_sorted[0][:3])

    endpoint_candidates = (
        (maximum, minimum),
        (bbox_max, bbox_min),
        (luma_max, luma_min),
    )
    best: tuple[int, int, int, int] | None = None
    for high, low in endpoint_candidates:
        color0, color1 = _ordered_565_pair(
            _pack_565(*high), _pack_565(*low), transparent_mode=transparent_mode
        )
        error, indices = _color_error(
            pixels,
            color0,
            color1,
            transparent_mode=transparent_mode,
            force_four_color=force_four_color,
        )
        candidate = (error, color0, color1, indices)
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    _error, color0, color1, indices = best
    return struct.pack("<HHI", color0, color1, indices)


def _encode_dxt1(rgba: bytes, width: int, height: int) -> bytes:
    blocks_x = max(1, (width + 3) // 4)
    blocks_y = max(1, (height + 3) // 4)
    out = bytearray(blocks_x * blocks_y * 8)
    cursor = 0
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            pixels = _block_pixels(rgba, width, height, block_x, block_y)
            transparent_mode = any(pixel[3] < 128 for pixel in pixels)
            block = _encode_color_block(
                pixels,
                transparent_mode=transparent_mode,
                force_four_color=False,
            )
            out[cursor : cursor + 8] = block
            cursor += 8
    return bytes(out)


def _alpha_error(alphas: list[int], alpha0: int, alpha1: int) -> tuple[int, int]:
    palette = _dxt5_alpha_palette(alpha0, alpha1)
    indices = 0
    error = 0
    for pixel_index, alpha in enumerate(alphas):
        selected = min(
            range(8),
            key=lambda index: (int(alpha) - int(palette[index])) ** 2,
        )
        error += (int(alpha) - int(palette[selected])) ** 2
        indices |= int(selected) << (3 * pixel_index)
    return error, indices


def _encode_alpha_block(pixels: list[tuple[int, int, int, int]]) -> bytes:
    alphas = [int(pixel[3]) for pixel in pixels]
    minimum = min(alphas)
    maximum = max(alphas)
    interior = [value for value in alphas if 0 < value < 255]
    candidates: set[tuple[int, int]] = {
        (maximum, minimum),
        (255, 0),
    }
    if interior:
        # Six-step mode reserves exact 0 and 255 entries and is often superior
        # for cutouts whose remaining alpha range is narrower.
        candidates.add((min(interior), max(interior)))
    best: tuple[int, int, int, int] | None = None
    for alpha0, alpha1 in candidates:
        if alpha0 == alpha1 and alpha0 not in {0, 255}:
            alpha0 = min(255, alpha0 + 1)
        error, indices = _alpha_error(alphas, alpha0, alpha1)
        candidate = (error, alpha0, alpha1, indices)
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    _error, alpha0, alpha1, indices = best
    return bytes((alpha0, alpha1)) + int(indices).to_bytes(6, "little")


def _encode_dxt5(rgba: bytes, width: int, height: int) -> bytes:
    blocks_x = max(1, (width + 3) // 4)
    blocks_y = max(1, (height + 3) // 4)
    out = bytearray(blocks_x * blocks_y * 16)
    cursor = 0
    for block_y in range(blocks_y):
        for block_x in range(blocks_x):
            pixels = _block_pixels(rgba, width, height, block_x, block_y)
            out[cursor : cursor + 8] = _encode_alpha_block(pixels)
            out[cursor + 8 : cursor + 16] = _encode_color_block(
                pixels,
                transparent_mode=False,
                force_four_color=True,
            )
            cursor += 16
    return bytes(out)


# ---------------------------------------------------------------------------
# Encoding-specific top-level conversion


def _decode_raw_bgra(raw: bytes, width: int, height: int) -> bytes:
    pixels = _deswizzle_raw(raw, width, height, 4)
    out = bytearray(width * height * 4)
    for offset in range(0, len(out), 4):
        blue, green, red, alpha = pixels[offset : offset + 4]
        out[offset : offset + 4] = bytes((red, green, blue, alpha))
    return bytes(out)


def _decode_grayscale(raw: bytes, width: int, height: int) -> bytes:
    pixels = _deswizzle_raw(raw, width, height, 1)
    out = bytearray(width * height * 4)
    for index, value in enumerate(pixels):
        target = index * 4
        out[target : target + 4] = bytes((value, value, value, 255))
    return bytes(out)


def _decode_top_level(raw: bytes, width: int, height: int, encoding: int) -> bytes:
    if encoding == TXB_ENCODING_BGRA:
        return _decode_raw_bgra(raw, width, height)
    if encoding == TXB_ENCODING_GRAYSCALE:
        return _decode_grayscale(raw, width, height)
    if encoding == TXB_ENCODING_DXT1:
        return _decode_dxt1(raw, width, height)
    if encoding == TXB_ENCODING_DXT5:
        return _decode_dxt5(raw, width, height)
    raise ValueError(f"Unsupported Jade TXB encoding 0x{encoding:02X}")


# ---------------------------------------------------------------------------
# Public API


def parse_txb_bytes(data: bytes, source_path: str = "") -> JadeTexture:
    view = BinaryView(data, source_path or "TXB")
    if len(view) < TXB_HEADER_SIZE:
        raise ValueError(
            f"TXB is too short: expected at least {TXB_HEADER_SIZE} bytes, got {len(view)}"
        )

    declared_data_size = view.u32(0, "TXB data size")
    unknown_float_1 = view.f32(4, "TXB header float 1")
    width = view.u16(8, "TXB width")
    height = view.u16(10, "TXB height")
    encoding = view.u8(12, "TXB encoding")
    mip_count = view.u8(13, "TXB mip count")
    flags = view.u16(14, "TXB flags")
    unknown_float_2 = view.f32(16, "TXB header float 2")

    if width == 0 or height == 0 or width >= 0x8000 or height >= 0x8000:
        raise ValueError(f"Invalid TXB dimensions {width}x{height}")
    if width * height > TXB_MAX_DECODED_PIXELS:
        raise ValueError(
            f"TXB dimensions {width}x{height} exceed the decode safety limit"
        )
    if mip_count == 0 or mip_count > TXB_MAX_MIP_COUNT:
        raise ValueError(f"Invalid TXB mip count {mip_count}")
    if encoding not in TXB_ENCODING_NAMES:
        raise ValueError(f"Unsupported Jade TXB encoding 0x{encoding:02X}")

    mipmaps = _mip_layout(width, height, encoding, mip_count)
    calculated_mip_size = sum(level.size for level in mipmaps)
    if declared_data_size < calculated_mip_size:
        raise ValueError(
            f"TXB payload is smaller than its mip chain: declared {declared_data_size}, "
            f"requires {calculated_mip_size}"
        )

    view.check(TXB_HEADER_SIZE, declared_data_size, "TXB declared pixel payload")
    for level in mipmaps:
        view.check(level.offset, level.size, f"TXB mip {level.level}")

    top = mipmaps[0]
    payload = view.bytes(top.offset, top.size, "TXB top mip")
    rgba = _decode_top_level(payload, width, height, encoding)

    padding_offset = TXB_HEADER_SIZE + calculated_mip_size
    payload_padding = view.bytes(
        padding_offset,
        declared_data_size - calculated_mip_size,
        "TXB opaque payload padding",
    )

    tail_offset = TXB_HEADER_SIZE + declared_data_size
    txi = ""
    if tail_offset < len(view):
        tail = view.bytes(tail_offset, len(view) - tail_offset, "TXB TXI tail")
        txi = tail.rstrip(b"\0\x1a\r\n ").decode("ascii", errors="replace")

    return JadeTexture(
        source_path=source_path,
        width=width,
        height=height,
        encoding=encoding,
        mip_count=mip_count,
        declared_data_size=declared_data_size,
        calculated_mip_size=calculated_mip_size,
        payload_padding_size=declared_data_size - calculated_mip_size,
        payload_padding=payload_padding,
        flags=flags,
        unknown_float_1=unknown_float_1,
        unknown_float_2=unknown_float_2,
        mipmaps=mipmaps,
        rgba=rgba,
        txi=txi,
    )


def parse_txb(path: str | os.PathLike[str]) -> JadeTexture:
    path = Path(path)
    return parse_txb_bytes(path.read_bytes(), str(path))


def _flip_rgba_rows(rgba: bytes | bytearray | memoryview, width: int, height: int) -> bytes:
    """Return RGBA8 bytes with vertical row order reversed.

    The decoded ``JadeTexture.rgba`` buffer is intentionally kept in native
    Jade/TXB row order for byte-faithful TXB round-tripping.  External image
    consumers used by Blender previews and KotOR/TSL sidecars expect the
    opposite row origin, so normalization happens only at this boundary.
    """

    width = int(width)
    height = int(height)
    row_size = width * 4
    data = bytes(rgba)
    if width <= 0 or height <= 0 or len(data) != row_size * height:
        raise ValueError(
            f"RGBA buffer length mismatch: expected {row_size * height}, got {len(data)}"
        )
    return b"".join(
        data[row * row_size : (row + 1) * row_size]
        for row in range(height - 1, -1, -1)
    )


def tga_bytes(texture: JadeTexture) -> bytes:
    expected = texture.width * texture.height * 4
    if len(texture.rgba) != expected:
        raise ValueError(
            f"RGBA buffer length mismatch: expected {expected}, got {len(texture.rgba)}"
        )

    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,  # image ID length
        0,  # no color map
        2,  # uncompressed true-color
        0,
        0,
        0,
        0,
        0,
        texture.width,
        texture.height,
        32,
        0x28,  # top-left origin, eight alpha bits
    )
    display_rgba = _flip_rgba_rows(texture.rgba, texture.width, texture.height)
    bgra = bytearray(expected)
    for offset in range(0, expected, 4):
        red, green, blue, alpha = display_rgba[offset : offset + 4]
        bgra[offset : offset + 4] = bytes((blue, green, red, alpha))
    return header + bytes(bgra)


def write_tga(texture: JadeTexture, path: str | os.PathLike[str]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tga_bytes(texture))
    return path

# ---------------------------------------------------------------------------
# TXB generation


def _swizzle_surface(linear: bytes, width: int, height: int, bytes_per_pixel: int) -> bytes:
    expected = width * height * bytes_per_pixel
    if len(linear) != expected:
        raise ValueError(
            f"Linear texture level has {len(linear)} bytes; expected {expected}"
        )
    out = bytearray(expected)
    for y in range(height):
        for x in range(width):
            target_pixel = _interleaved_offset(x, y, width, height)
            source = (y * width + x) * bytes_per_pixel
            target = target_pixel * bytes_per_pixel
            if target + bytes_per_pixel > expected:
                raise ValueError(
                    f"Swizzle offset {target_pixel} lies outside {width}x{height} surface"
                )
            out[target : target + bytes_per_pixel] = linear[
                source : source + bytes_per_pixel
            ]
    return bytes(out)


def _swizzle_raw(linear: bytes, width: int, height: int, bytes_per_pixel: int) -> bytes:
    """Mirror :func:`_deswizzle_raw` for generated uncompressed TXBs."""

    expected = width * height * bytes_per_pixel
    if len(linear) != expected:
        raise ValueError(
            f"Linear texture level has {len(linear)} bytes; expected {expected}"
        )
    if not _is_power_of_two(width):
        return bytes(linear)
    if height == width * 6:
        face_size = width * width * bytes_per_pixel
        return b"".join(
            _swizzle_surface(
                linear[face * face_size : (face + 1) * face_size],
                width,
                width,
                bytes_per_pixel,
            )
            for face in range(6)
        )
    return _swizzle_surface(linear, width, height, bytes_per_pixel)


def _downsample_rgba_surface(rgba: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    next_width = max(1, width >> 1)
    next_height = max(1, height >> 1)
    out = bytearray(next_width * next_height * 4)
    for y in range(next_height):
        source_y0 = min(height - 1, y * 2)
        source_y1 = min(height - 1, source_y0 + 1)
        for x in range(next_width):
            source_x0 = min(width - 1, x * 2)
            source_x1 = min(width - 1, source_x0 + 1)
            samples = (
                (source_y0 * width + source_x0) * 4,
                (source_y0 * width + source_x1) * 4,
                (source_y1 * width + source_x0) * 4,
                (source_y1 * width + source_x1) * 4,
            )
            target = (y * next_width + x) * 4
            for channel in range(4):
                out[target + channel] = int(
                    round(sum(rgba[index + channel] for index in samples) / 4.0)
                )
    return bytes(out), next_width, next_height


def _downsample_rgba(rgba: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    """Generate one box-filtered mip, keeping stacked cube faces independent."""

    if height == width * 6:
        face_size = width * width * 4
        faces: list[bytes] = []
        next_width = max(1, width >> 1)
        for face in range(6):
            level, level_width, level_height = _downsample_rgba_surface(
                rgba[face * face_size : (face + 1) * face_size], width, width
            )
            if level_width != next_width or level_height != next_width:
                raise ValueError("Internal cube-map mip generation mismatch")
            faces.append(level)
        return b"".join(faces), next_width, next_width * 6
    return _downsample_rgba_surface(rgba, width, height)


def _full_mip_count(width: int, height: int) -> int:
    if height == width * 6:
        height = width
    count = 1
    while width > 1 or height > 1:
        width = max(1, width >> 1)
        height = max(1, height >> 1)
        count += 1
    return count


def _rgba_to_bgra(rgba: bytes) -> bytes:
    out = bytearray(len(rgba))
    for offset in range(0, len(rgba), 4):
        red, green, blue, alpha = rgba[offset : offset + 4]
        out[offset : offset + 4] = bytes((blue, green, red, alpha))
    return bytes(out)


def _rgba_to_grayscale(rgba: bytes) -> bytes:
    out = bytearray(len(rgba) // 4)
    for index, offset in enumerate(range(0, len(rgba), 4)):
        red, green, blue, _alpha = rgba[offset : offset + 4]
        # Jade's grayscale textures represent intensity, not alpha.  Rec.709
        # weights give a deterministic conversion for newly authored images.
        out[index] = max(
            0,
            min(255, int(round(0.2126 * red + 0.7152 * green + 0.0722 * blue))),
        )
    return bytes(out)


def txb_bytes_from_rgba(
    width: int,
    height: int,
    rgba: bytes | bytearray,
    *,
    encoding: int = TXB_ENCODING_BGRA,
    mip_count: int | None = None,
    flags: int | None = None,
    unknown_float_1: float | None = None,
    unknown_float_2: float | None = None,
    payload_padding: bytes | bytearray | memoryview = b"",
    txi: str = "",
) -> bytes:
    """Build a native Jade PC TXB from a top-level RGBA8 surface.

    All four observed Jade PC encodings are supported.  DXT1 and DXT5 use a
    deterministic, dependency-free block compressor so edited retail textures
    can retain their native storage class instead of silently expanding to
    BGRA8.  Compression is lossy by definition; raw BGRA remains available for
    workflows that require pixel-exact authored output.
    """

    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0 or width >= 0x8000 or height >= 0x8000:
        raise ValueError(f"Invalid TXB dimensions {width}x{height}")
    rgba = bytes(rgba)
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(f"RGBA buffer length mismatch: expected {expected}, got {len(rgba)}")
    if encoding not in TXB_ENCODING_NAMES:
        raise ValueError(f"Unsupported Jade TXB encoding 0x{encoding:02X}")

    maximum_mips = _full_mip_count(width, height)
    if mip_count is None:
        mip_count = maximum_mips
    mip_count = int(mip_count)
    if not 1 <= mip_count <= min(maximum_mips, TXB_MAX_MIP_COUNT):
        raise ValueError(
            f"Invalid TXB mip count {mip_count}; valid range is 1..{maximum_mips}"
        )

    if flags is None:
        flags = 0x0001 if encoding == TXB_ENCODING_GRAYSCALE else 0x0101
    if unknown_float_1 is None:
        unknown_float_1 = sum(rgba[3::4]) / (255.0 * width * height)
    if unknown_float_2 is None:
        grayscale = _rgba_to_grayscale(rgba)
        unknown_float_2 = sum(grayscale) / (255.0 * width * height)

    payload = bytearray()
    level_rgba = rgba
    level_width = width
    level_height = height
    for _level in range(mip_count):
        if encoding == TXB_ENCODING_BGRA:
            linear = _rgba_to_bgra(level_rgba)
            payload.extend(_swizzle_raw(linear, level_width, level_height, 4))
        elif encoding == TXB_ENCODING_GRAYSCALE:
            linear = _rgba_to_grayscale(level_rgba)
            payload.extend(_swizzle_raw(linear, level_width, level_height, 1))
        elif encoding == TXB_ENCODING_DXT1:
            payload.extend(_encode_dxt1(level_rgba, level_width, level_height))
        else:
            payload.extend(_encode_dxt5(level_rgba, level_width, level_height))
        if _level + 1 < mip_count:
            level_rgba, level_width, level_height = _downsample_rgba(
                level_rgba, level_width, level_height
            )

    # The header's declared data region is not necessarily identical to the
    # compact mip-chain length.  Retail resources can carry an opaque suffix
    # after the last mip.  Jade/xoreos consume the compact levels first and
    # seek to ``header + declared_data_size`` before reading TXI, so an edited
    # texture must retain that suffix when its dimensions/layout are unchanged.
    payload_padding = bytes(payload_padding)
    declared_payload = bytes(payload) + payload_padding

    header = bytearray(TXB_HEADER_SIZE)
    struct.pack_into(
        "<I f HH BB H f",
        header,
        0,
        len(declared_payload),
        float(unknown_float_1),
        width,
        height,
        encoding,
        mip_count,
        int(flags) & 0xFFFF,
        float(unknown_float_2),
    )
    tail = str(txi or "").encode("ascii", errors="replace")
    return bytes(header) + declared_payload + tail


def txb_bytes(texture: JadeTexture, *, preserve_encoding: bool = False) -> bytes:
    """Serialize a decoded texture.

    ``preserve_encoding`` now applies to all four known retail encodings.  The
    default remains backward compatible: edited DXT resources are expanded to
    BGRA8 unless callers explicitly request native recompression.
    """

    encoding = texture.encoding
    if encoding in {TXB_ENCODING_DXT1, TXB_ENCODING_DXT5} and not preserve_encoding:
        encoding = TXB_ENCODING_BGRA
    return txb_bytes_from_rgba(
        texture.width,
        texture.height,
        texture.rgba,
        encoding=encoding,
        mip_count=texture.mip_count,
        flags=texture.flags,
        unknown_float_1=texture.unknown_float_1,
        unknown_float_2=texture.unknown_float_2,
        payload_padding=texture.payload_padding,
        txi=texture.txi,
    )


def write_txb_from_rgba(
    path: str | os.PathLike[str],
    width: int,
    height: int,
    rgba: bytes | bytearray,
    **kwargs,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(txb_bytes_from_rgba(width, height, rgba, **kwargs))
    return path


def write_txb(
    texture: JadeTexture,
    path: str | os.PathLike[str],
    *,
    preserve_encoding: bool = False,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(txb_bytes(texture, preserve_encoding=preserve_encoding))
    return path
