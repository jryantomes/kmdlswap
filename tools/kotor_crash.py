r"""Read a KOTOR crash dump: where it died, and how it got there.

Windows writes a dump to %LOCALAPPDATA%\CrashDumps when the game crashes
(full dumps - the whole address space - once the LocalDumps DumpType=2 key is
set for swkotor.exe). This reads it without a debugger:

  * the exception: what kind, at which address, reading or writing where
  * the faulting instruction and the ones around it, disassembled
  * the registers at the moment of the crash
  * the call stack, recovered by scanning the stack for return addresses into
    loaded modules (each one checked to follow a real CALL instruction, which
    weeds out most stale values)
  * with --scripts: which of the mod's scripts the game had in memory, by
    looking for their names in the heap - a hint at what was running

Addresses inside swkotor.exe are also given relative to the image base
0x400000, the same numbers the notes use (e.g. swkotor+0x16e549).

usage: kotor_crash.py [dump]            newest swkotor dump if none given
       kotor_crash.py [dump] --scripts
"""
import os
import struct
import sys
from pathlib import Path

DUMPS = Path(os.environ.get("LOCALAPPDATA", "")) / "CrashDumps"
CODES = {0xC0000005: "access violation", 0xC0000094: "integer divide by zero",
         0xC00000FD: "stack overflow", 0xC0000409: "stack buffer overrun (fail-fast)",
         0x80000003: "breakpoint", 0xC000001D: "illegal instruction",
         0xE06D7363: "C++ exception", 0xC0000374: "heap corruption"}


class Dump:
    def __init__(self, path):
        self.f = open(path, "rb")
        sig, _ver, n, rva = struct.unpack("<4sIII", self.read(0, 16))
        if sig != b"MDMP":
            raise SystemExit(f"{path} is not a minidump")
        self.streams = {}
        for i in range(n):
            kind, size, at = struct.unpack("<III", self.read(rva + 12 * i, 12))
            self.streams[kind] = (at, size)
        self.modules = self._modules()
        self.ranges = self._memory()

    def read(self, at, size):
        self.f.seek(at)
        return self.f.read(size)

    def _modules(self):
        at, _ = self.streams[4]
        (count,) = struct.unpack("<I", self.read(at, 4))
        out = []
        for i in range(count):
            m = self.read(at + 4 + 108 * i, 108)
            base, size = struct.unpack("<QI", m[:12])
            (name_rva,) = struct.unpack("<I", m[20:24])
            (length,) = struct.unpack("<I", self.read(name_rva, 4))
            name = self.read(name_rva + 4, length).decode("utf-16-le")
            out.append((base, size, Path(name.replace("\\", "/")).name))
        return sorted(out)

    def _memory(self):
        if 9 in self.streams:                              # full dump
            at, _ = self.streams[9]
            count, base = struct.unpack("<QQ", self.read(at, 16))
            out, where = [], base
            for i in range(count):
                start, size = struct.unpack("<QQ", self.read(at + 16 + 16 * i, 16))
                out.append((start, size, where))
                where += size
            return out
        at, _ = self.streams[5]                            # small dump
        (count,) = struct.unpack("<I", self.read(at, 4))
        out = []
        for i in range(count):
            start, size, rva = struct.unpack("<QII", self.read(at + 4 + 16 * i, 16))
            out.append((start, size, rva))
        return out

    def mem(self, addr, size):
        for start, length, rva in self.ranges:
            if start <= addr and addr + size <= start + length:
                return self.read(rva + addr - start, size)
        return None

    def where(self, addr):
        for base, size, name in self.modules:
            if base <= addr < base + size:
                if name.lower() == "swkotor.exe":
                    return f"swkotor+0x{addr - 0x400000:x}"
                return f"{name}+0x{addr - base:x}"
        return None

    def exception(self):
        at, _ = self.streams[6]
        tid, = struct.unpack("<I", self.read(at, 4))
        code, flags, _rec, addr, nparams = struct.unpack("<IIQQI", self.read(at + 8, 28))
        params = struct.unpack("<15Q", self.read(at + 40, 120))[:nparams]
        ctx_size, ctx_rva = struct.unpack("<II", self.read(at + 160, 8))
        return tid, code, addr, params, self.read(ctx_rva, ctx_size)


def registers(ctx):
    names = ["edi", "esi", "ebx", "edx", "ecx", "eax", "ebp", "eip"]
    regs = dict(zip(names, struct.unpack("<8I", ctx[156:188])))
    regs["esp"], = struct.unpack("<I", ctx[196:200])
    return regs


def disasm(d, addr, before=24, after=16):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    # start a little early and keep the line that lands on the address
    for back in range(before, -1, -1):
        code = d.mem(addr - back, back + after)
        if code is None:
            continue
        lines = list(md.disasm(code, addr - back))
        if any(i.address == addr for i in lines):
            return [(i.address, f"{i.mnemonic} {i.op_str}") for i in lines]
    code = d.mem(addr, after)
    return [(i.address, f"{i.mnemonic} {i.op_str}") for i in md.disasm(code or b"", addr)]


def follows_call(d, ret):
    """Is ret the address just after a CALL? (E8 rel32, FF /2 in its forms)"""
    b = d.mem(ret - 7, 7)
    if not b:
        return False
    if b[2] == 0xE8:                                   # call rel32
        return True
    for back in (2, 3, 6, 7):                          # call [reg], [reg+d8], [reg+d32], [abs]
        op = b[7 - back:]
        if op[0] == 0xFF and (op[1] >> 3) & 7 == 2:
            return True
    return False


def stack(d, esp, words=2048):
    data = d.mem(esp, words * 4)
    while data is None and words > 16:
        words //= 2
        data = d.mem(esp, words * 4)
    out = []
    for i, (v,) in enumerate(struct.iter_unpack("<I", data or b"")):
        name = d.where(v)
        if name and follows_call(d, v):
            out.append((esp + 4 * i, v, name))
    return out


def scripts_in_heap(d, prefixes=(b"rfk_", b"dbg_", b"hkrfkjr", b"k_hen_", b"k_pdan_")):
    """Names of the mod's scripts found anywhere in memory, with how often."""
    import re
    pattern = re.compile(rb"(?:" + b"|".join(prefixes) + rb")[a-z0-9_]{1,12}")
    seen = {}
    for _start, length, rva in d.ranges:
        if length > 64 << 20:
            continue
        for m in pattern.finditer(d.read(rva, length)):
            name = m.group().decode()
            seen[name] = seen.get(name, 0) + 1
    return seen


def main(argv):
    flags = [a for a in argv if a.startswith("--")]
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else max(DUMPS.glob("swkotor*.dmp"), key=lambda p: p.stat().st_mtime)
    d = Dump(path)
    tid, code, addr, params, ctx = d.exception()
    kind = CODES.get(code, f"0x{code:08x}")
    print(f"{path.name}  ({path.stat().st_size >> 20} MB, {'full' if 9 in d.streams else 'small'} dump)")
    print(f"\n{kind} in thread {tid} at 0x{addr:08x}  {d.where(addr) or '(no module)'}")
    if code == 0xC0000005 and len(params) >= 2:
        verb = {0: "reading", 1: "writing", 8: "executing"}.get(params[0], "touching")
        print(f"  {verb} 0x{params[1]:08x}" + ("  <- a null pointer, or near one" if params[1] < 0x10000 else ""))

    regs = registers(ctx)
    print("\nregisters: " + "  ".join(f"{k}={v:08x}" for k, v in regs.items()))

    print("\nthe faulting instruction (>>) and its neighbours:")
    for a, text in disasm(d, addr):
        print(f"  {'>>' if a == addr else '  '} {d.where(a) or hex(a):22} {text}")

    print("\ncall stack (return addresses on the stack that follow a CALL):")
    frames = stack(d, regs["esp"])
    for slot, ret, name in frames[:40]:
        print(f"  [esp+0x{slot - regs['esp']:04x}]  {name}")
    if not frames:
        print("  (the stack memory is not in this dump)")

    if "--scripts" in flags:
        print("\nthe mod's script names found in memory (count):")
        for name, n in sorted(scripts_in_heap(d).items(), key=lambda kv: -kv[1])[:40]:
            print(f"  {n:6}  {name}")


if __name__ == "__main__":
    main(sys.argv[1:])
