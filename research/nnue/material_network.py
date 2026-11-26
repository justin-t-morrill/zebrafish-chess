"""Prepare Bullet warm starts and package four-head Chess768 networks for UCI."""
import argparse
import struct
from pathlib import Path


def weight_blocks(data):
    """Read the named float32 arrays from a plain Chess768 Bullet checkpoint."""
    blocks = {}
    offset = 0
    while offset < len(data):
        end = data.index(b"\n", offset) + 1
        name = data[offset:end - 1].decode("ascii")
        count, = struct.unpack_from("<Q", data, end)
        value_start = end + 8
        next_offset = value_start + 4 * count
        values = data[value_start:next_offset]
        if len(values) != 4 * count or name in blocks:
            raise ValueError(f"invalid weight block {name}")
        blocks[name] = values
        offset = next_offset
    if set(blocks) != {"l0w", "l0b", "l1w", "l1b"}:
        raise ValueError("expected l0w, l0b, l1w and l1b for plain Chess768")
    return blocks


def write_blocks(blocks):
    chunks = []
    for name, values in blocks.items():
        chunks.extend((name.encode("ascii") + b"\n", struct.pack("<Q", len(values) // 4), values))
    return b"".join(chunks)


def expand_single_head(data):
    """Duplicate each single-output coefficient in Bullet's column-major layout."""
    blocks = weight_blocks(data)
    for name, values in blocks.items():
        if name in ("l1w", "l1b"):
            if name == "l1b" and len(values) != 4:
                raise ValueError("expected a single-output starting checkpoint")
            blocks[name] = b"".join(values[i:i + 4] * 4 for i in range(0, len(values), 4))
    return write_blocks(blocks)


def merge_channel_pairs(data):
    """Merge paired descendants of a 256-wide initialization in a 512-wide net."""
    import numpy as np

    blocks = weight_blocks(data)
    shapes = {"l0w": (768, 512), "l0b": (1, 512), "l1w": (2, 512, 4), "l1b": (4,)}
    weights = {key: np.frombuffer(blocks[key], dtype="<f4").reshape(shape) for key, shape in shapes.items()}
    left, right = np.split(weights["l1w"], 2, axis=1)
    combined = left + right
    # Fit one input mixture to the readout weights for four heads and both sides.
    magnitude = np.square(combined).sum(axis=(0, 2))
    mixture = np.divide((left * combined).sum(axis=(0, 2)), magnitude,
                        out=np.full(256, 0.5), where=magnitude > 1e-15).clip(0, 1)
    merged = {}
    for key in ("l0w", "l0b"):
        left, right = np.split(weights[key], 2, axis=1)
        merged[key] = (left * mixture + right * (1 - mixture)).astype("<f4").tobytes()
    merged["l1w"] = combined.astype("<f4").tobytes()
    merged["l1b"] = blocks["l1b"]
    return write_blocks(merged)


def pack_four_heads(data, width):
    """Bullet exports transposed output rows, followed by all four biases."""
    shared_bytes = 2 * (768 + 1) * width
    row_bytes = 2 * 2 * width
    bias_start = shared_bytes + 4 * row_bytes
    raw_size = bias_start + 8
    if len(data) not in (raw_size, (raw_size + 63) & ~63):
        raise ValueError(f"unexpected network size for width {width}")
    result = bytearray(struct.pack("<8sII", b"ZBHEAD01", width, 4))
    result.extend(data[:shared_bytes])
    for bucket in range(4):
        row = shared_bytes + bucket * row_bytes
        result.extend(data[row:row + row_bytes])
        bias = bias_start + 2 * bucket
        result.extend(data[bias:bias + 2])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    expand = commands.add_parser("expand", help="expand optimiser_state/weights.bin from one to four outputs")
    merge = commands.add_parser("merge-pairs", help="merge a paired 512-wide four-head model into a 256-wide warm start")
    pack = commands.add_parser("pack", help="package a material-heads quantised.bin checkpoint")
    for command in (expand, merge, pack):
        command.add_argument("input", type=Path)
        command.add_argument("output", type=Path)
    pack.add_argument("--width", type=int, required=True, choices=(128, 256, 512))
    args = parser.parse_args()
    data = args.input.read_bytes()
    if args.command == "expand":
        result = expand_single_head(data)
    elif args.command == "merge-pairs":
        result = merge_channel_pairs(data)
    else:
        result = pack_four_heads(data, args.width)
    args.output.write_bytes(result)


if __name__ == "__main__":
    main()
