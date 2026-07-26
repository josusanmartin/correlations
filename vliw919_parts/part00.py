from __future__ import annotations

from collections import defaultdict
import base64 as _transfer_b64
import heapq
import pickle as _transfer_pickle
import random
import os
import zlib as _transfer_zlib

from problem import DebugInfo, HASH_STAGES, SLOT_LIMITS, VLEN, SCRATCH_SIZE


class _TNode:
    __slots__ = (
        "idx", "kind", "reads", "writes", "vector_slot", "flow_slot",
        "load_slot", "store_slot", "lane_slots", "deps", "users",
        "rank", "ready_at", "remaining_chunks", "placements",
    )

    def __init__(
        self,
        idx: int,
        kind: str,
        reads: list[tuple],
        writes: list[tuple],
        *,
        vector_slot: tuple | None = None,
        flow_slot: tuple | None = None,
        load_slot: tuple | None = None,
        store_slot: tuple | None = None,
        lane_slots: list[tuple] | None = None,
    ) -> None:
        self.idx = idx
        self.kind = kind
        self.reads = reads
        self.writes = writes
        self.vector_slot = vector_slot
        self.flow_slot = flow_slot
        self.load_slot = load_slot
        self.store_slot = store_slot
        self.lane_slots = lane_slots
        self.deps: set[int] = set()
        self.users: list[int] = []
        self.rank: float = 0.0
        self.ready_at = 0
        self.remaining_chunks = 0
        self.placements: list[tuple[int, str, list[tuple]]] = []


class _CompactColdProgram(list):
    """Lazy complete program that is also recognized as a JSON list."""

    def __init__(self, hot, tables):
        self.hot = hot
        self.tables = sorted(tables, key=lambda row: row["base"])
        self.starts = [row["base"] for row in self.tables]
        self.total = max(
            [len(hot)] + [row["base"] + row["count"] for row in self.tables]
        )

    def __len__(self):
        return self.total

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(self.total)
            return [self[i] for i in range(start, stop, step)]
        if index < 0:
            index += self.total
        if index < 0 or index >= self.total:
            raise IndexError(index)
        if index < len(self.hot):
            return self.hot[index]
        from bisect import bisect_right
        at = bisect_right(self.starts, index) - 1
        if at < 0:
            raise IndexError(index)
        row = self.tables[at]
        packed = index - row["base"]
        if packed < 0 or packed >= row["count"]:
            raise IndexError(index)
        chunk = row["chunk"]
        positions = [
            (packed >> (4 * (chunk - 1 - j))) & 15
            for j in range(chunk)
        ]
        digit_map = row.get("digit_map")
        if digit_map is not None:
            positions = [digit_map.get(position, 0) for position in positions]
        entry = {engine: list(slots) for engine, slots in row["copied"].items()}
        entry.setdefault("alu", []).extend([
            (
                "^", row["current_base"] + row["lane0"] + j,
                row["current_base"] + row["lane0"] + j,
                row["node_scalars"][position],
            )
            for j, position in enumerate(positions)
        ])
        if row.get("prepare_pairs"):
            yes_base, no_base = row["prepare_pair_bases"]
            pair_nodes = row["prepare_node_scalars"]
            entry["alu"].extend(
                ("|", yes_base + row["lane0"] + j,
                 pair_nodes[2 * position + 1],
                 pair_nodes[2 * position + 1])
                for j, position in enumerate(positions)
            )
            entry["alu"].extend(
                ("|", no_base + row["lane0"] + j,
                 pair_nodes[2 * position],
                 pair_nodes[2 * position])
                for j, position in enumerate(positions)
            )
        entry["flow"] = [row["flow"]]
        return entry

    def __iter__(self):
        for i in range(self.total):
            yield self[i]


class _TransferredCompiler:
    """Independent implementation of the transferred reverse-tree pipeline."""

    CAPS = {"alu": 12, "valu": 6, "load": 2, "store": 2, "flow": 1}

    def __init__(self, *, search_rounds: int = 192) -> None:
        self.instructions: list[dict[str, list[tuple]]] = []
        self.nodes: list[_TNode] = []
        self._next_scalar = 0
        self._next_vector = 0
        self._constants: dict[int, int] = {}
        self._last_def: dict[tuple, int] = {}
        self._debug: dict[int, tuple[str, int]] = {}
        self._bias: list[float] = []
        self._phase: list[int] = []
        self._tags: list[tuple[int, int]] = []
        self._active_group = -1
        self._active_round = -1
        self.search_rounds = search_rounds
        self.physical_high_water = 0
        self._r4_q8_chains: list[dict] = []
        self._cold_dispatch_latency: dict[int, int] = {}
        self._cold_table_cursor = 0
        self._cold_stage_index = 0
        self._cold_base_chain_state: dict[int, tuple[int, int]] = {}
        self._cold_base_roots: list[tuple[int, int, int]] = []
        self._cold_shared_root_cell: int | None = None
        self._cold_shared_root_relative: int | None = None
        self._cold_root_cells: dict[int, int] = {}
        self._cold_synth_scalars: dict[int, int] = {}
        self._control_carry_k_cell: int | None = None
        self._control_carry_k_node: int | None = None
        self._packed_broadcast_ordinal = 0

    @staticmethod
    def _is_vref(x) -> bool:
        return isinstance(x, tuple) and len(x) == 2 and x[0] == "vr"

    @classmethod
    def _dep(cls, x) -> tuple:
        return ("v", x[1]) if cls._is_vref(x) else ("p", x)

    @classmethod
    def _tpl(cls, x):
        return ("V", x[1]) if cls._is_vref(x) else x

    @classmethod
    def _lane_tpl(cls, x, lane: int):
        return ("L", x[1], lane) if cls._is_vref(x) else x + lane

    def _new_vref(self):
        out = ("vr", self._next_vector)
        self._next_vector += 1
        return out

    def _reserve(self, length: int = 1, name: str | None = None) -> int:
        base = self._next_scalar
        self._next_scalar += length
        if name is not None:
            self._debug[base] = (name, length)
        if self._next_scalar > SCRATCH_SIZE:
            raise RuntimeError("fixed scratch allocation overflow")
        return base

    def _emit(
        self,
        kind: str,
        reads: list[tuple],
        writes: list[tuple],
        **slots,
    ) -> _TNode:
        node = _TNode(len(self.nodes), kind, reads, writes, **slots)
        self.nodes.append(node)
        self._tags.append((self._active_group, self._active_round))
        for loc in reads:
            if loc[0] == "v":
                for lane in range(VLEN):
                    writer = self._last_def.get(("vl", loc[1], lane))
                    if writer is not None:
                        node.deps.add(writer)
            writer = self._last_def.get(loc)
            if writer is not None:
                node.deps.add(writer)
        for loc in writes:
            self._last_def[loc] = node.idx
        return node

    def _const(self, value: int, *, via_flow: bool = False) -> int:
        value &= 0xFFFFFFFF
        existing = self._constants.get(value)
        if existing is not None:
            return existing
        if via_flow:
            zero = self._const(0)
            addr = self._reserve()
            self._emit(
                "flow_only", [("p", zero)], [("p", addr)],
                flow_slot=("add_imm", addr, zero, value),
            )
        else:
            addr = self._reserve()
            if value:
                self._emit(
                    "load", [], [("p", addr)],
                    load_slot=("const", addr, value),
                )
        self._constants[value] = addr
        return addr

    def _broadcast_into(self, dest, scalar: int, *, virtual: bool) -> _TNode:
        lane_slots = [
            ("|", self._lane_tpl(dest, k), scalar, scalar)
            for k in range(VLEN)
        ]
        return self._emit(
            "flex", [("p", scalar)],
            [("v", dest[1])] if virtual else [("p", dest)],
            vector_slot=("vbroadcast", self._tpl(dest), scalar),
            lane_slots=lane_slots,
        )

    def _broadcast(self, value: int, *, flow_const: bool = False) -> int:
        value &= 0xFFFFFFFF
        ordinal = self._packed_broadcast_ordinal
        self._packed_broadcast_ordinal += 1
        packed_mask = int(os.getenv("TRANSFER_PACKED_CONST_BCAST_MASK", "0"), 0)
        packed = (os.getenv("TRANSFER_PACKED_CONST_BCAST", "0") != "0"
                  or ((packed_mask >> ordinal) & 1) != 0)
        if packed and value not in self._constants:
            dest = self._reserve(VLEN)
            if flow_const:
                zero = self._const(0)
                self._emit(
                    "flow_only", [("p", zero)], [("p", dest)],
                    flow_slot=("add_imm", dest, zero, value),
                )
            elif value:
                self._emit(
                    "load", [], [("p", dest)],
                    load_slot=("const", dest, value),
                )
            self._constants[value] = dest
            copies = [
                ("|", dest + lane, dest, dest) for lane in range(1, VLEN)
            ]
            self._emit(
                "alu8", [("p", dest)], [("p", dest)], lane_slots=copies,
            )
            return dest
        scalar = self._const(value, via_flow=flow_const)
        dest = self._reserve(VLEN)
        self._broadcast_into(dest, scalar, virtual=False)
        return dest

    def _ensure_stage_bank(self, bank: int):
        banks = getattr(self, "_node_stage_banks", None)
        if banks is None:
            banks = self._node_stage_banks = {}
        state = banks.get(bank)
        if state is not None:
            return state
        base_value = (0 if bank == 0 else
                      self._node_stage_extra_base + VLEN * (bank - 1))
        base = self._const(base_value)
        one = self._const(1, via_flow=True)
        addrs = [base]
        for _ in range(1, VLEN):
            addr = self._reserve()
            self._emit(
                "salu", [("p", addrs[-1]), ("p", one)], [("p", addr)],
                lane_slots=[("+", addr, addrs[-1], one)],
            )
            addrs.append(addr)
        state = {"addrs": tuple(addrs), "last_load": None}
        banks[bank] = state
        return state

    def _staged_broadcast_lane_fixed(self, src, lane: int, bank: int) -> int:
        state = self._ensure_stage_bank(bank)
        scalar_tpl = self._lane_tpl(src, lane)
        stores = []
        for addr in state["addrs"]:
            node = self._emit(
                "store", [("p", addr), self._dep(src)], [],
                store_slot=("store", addr, scalar_tpl),
            )
            if state["last_load"] is not None:
                node.deps.add(state["last_load"])
            stores.append(node.idx)
        dest = self._reserve(VLEN)
        load = self._emit(
            "load", [("p", state["addrs"][0])], [("p", dest)],
            load_slot=("vload", dest, state["addrs"][0]),
        )
        load.deps.update(stores)
        state["last_load"] = load.idx
        return dest

    def _broadcast_lane_fixed(self, src, lane: int) -> int:
        ordinal = getattr(self, "_fixed_lane_bcast_ordinal", 0)
        self._fixed_lane_bcast_ordinal = ordinal + 1
        stage_mask = int(os.getenv("TRANSFER_STAGE_NODE_BCAST_MASK", "0"), 0)
        if ((stage_mask >> ordinal) & 1) != 0:
            bank_count = max(1, int(os.getenv("TRANSFER_STAGE_NODE_BCAST_BANKS", "1")))
            staged_index = getattr(self, "_staged_node_bcast_count", 0)
            self._staged_node_bcast_count = staged_index + 1
            return self._staged_broadcast_lane_fixed(
                src, lane, staged_index % bank_count
            )
        dest = self._reserve(VLEN)
        scalar_tpl = self._lane_tpl(src, lane)
        lane_slots = [
            ("|", dest + k, scalar_tpl, scalar_tpl) for k in range(VLEN)
        ]
        self._emit(
            "flex", [self._dep(src)], [("p", dest)],
            vector_slot=("vbroadcast", dest, scalar_tpl),
            lane_slots=lane_slots,
        )
        return dest

    def _broadcast_lane_temp(self, src, lane: int):
