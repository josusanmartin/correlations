        ) & prepare_final_mask
        r14_special_code_mask = int(
            os.getenv("TRANSFER_R14_SPECIAL_CODE_MASK", "0"), 0
        ) & prepare_final_mask
        r14_two_select_mask = int(
            os.getenv("TRANSFER_R14_TWO_SELECT_MASK", "0"), 0
        ) & prepare_final_mask
        r14_special_code_mask &= ~r14_two_select_mask
        r14_tail2_mask &= ~(r14_special_code_mask | r14_two_select_mask)
        if pfold_groups or pfold_mask:
            four_vec = self._broadcast(4, flow_const=True)
            reverse_entry4_plus2 = self._broadcast((1 << 4) + 4,
                                                   flow_const=True)
        else:
            four_vec = reverse_entry4_plus2 = None
        three_vec = None
        r14_entry3_plus2 = r14_entry3_plus3 = None
        if r14_tail2_mask:
            if four_vec is None:
                four_vec = self._vector_flex("+", two_vec, two_vec)
            r14_entry3_plus2 = self._vector_flex(
                "+", reverse_entry[3], two_vec
            )
            r14_entry3_plus3 = self._vector_flex(
                "+", reverse_entry_plus1[3], two_vec
            )
        if tail2_flow_mask:
            if four_vec is None:
                four_vec = self._vector_flex("+", two_vec, two_vec)
            three_vec = self._vector_flex("+", two_vec, one_vec)

        def path_mode(round_idx: int, group: int) -> str:
            depth = round_idx % level_count
            if depth == 0:
                return "root"
            if (depth == 3 and round_idx == rounds - 2
                    and (((control_carry_mask | prepare_final_mask)
                          >> group) & 1)):
                return "cold"
            if depth == 3 and round_idx == 3 and group < early_d3_groups:
                return "gather"
            if depth == 4 and round_idx == 4 and ((r4_t8_mask >> group) & 1):
                return "cold"
            if (depth == 4 and round_idx == rounds - 1
                    and ((prepare_final_mask >> group) & 1)):
                return "prepared"
            if (depth == 4 and round_idx == rounds - 1
                    and ((r15_t8_mask >> group) & 1)):
                return "cold"
            if depth == 4 and round_idx != 4 and is_final_blend(group):
                return "blend"
            if depth >= 5 or (depth == 4 and round_idx != 4):
                return "gather"
            if depth == 4 and group < early_d4_groups:
                return "gather"
            return "blend"

        def needs_address(round_idx: int, group: int) -> bool:
            return path_mode(round_idx, group) in ("gather", "cold")

        pass_has_gather = {
            (start, group): any(
                needs_address(r, group)
                for r in range(start, min(start + level_count, rounds))
            )
            for start in range(0, rounds, level_count)
            for group in range(groups)
        }

        raw_offsets = (0, 7, 15, 23)
        raw_vecs = []
        raw_load_ids: list[int] = []
        raw_addresses: dict[int, int] = {}
        for offset in raw_offsets:
            addr = self._const(tree_base + offset)
            raw_addresses[offset] = addr
            vec = self._new_vref()
            load = self._emit(
                "load", [("p", addr)], [("v", vec[1])],
                load_slot=("vload", self._tpl(vec), addr),
            )
            raw_vecs.append(vec)
            raw_load_ids.append(load.idx)

        def reverse_and_adjust(vec):
            dest = self._new_vref()
            slots = [
                ("^", self._lane_tpl(dest, lane),
                 self._lane_tpl(vec, VLEN - 1 - lane), sc["c6"])
                for lane in range(VLEN)
            ]
            self._emit(
                "alu8", [self._dep(vec), ("p", sc["c6"])],
                [("v", dest[1])], lane_slots=slots,
            )
            return dest

        adjusted = [self._vector_flex("^", raw_vecs[0], vc["c6"],
                                      scalar_b=sc["c6"])]
        adjusted.extend(reverse_and_adjust(v) for v in raw_vecs[1:])

        def adjusted_node(index: int):
            if index < 7:
                return adjusted[0], index
            if index < 15:
                return adjusted[1], 14 - index
            if index < 23:
                return adjusted[2], 22 - index
            return adjusted[3], 30 - index

        r4_t8_nodes = None
        r4_t8_node_reads = None
        r4_t8_shift4 = None
        r4_t8_shift8 = None
        if r4_t8_mask or r15_t8_mask or prepare_final_mask:
            direct_node_lanes = (
                os.getenv("TRANSFER_COLD_DIRECT_NODE_LANES", "0") != "0"
            )
            r4_t8_nodes = []
            r4_t8_node_reads_list = []
            for path_value in range(16):
                vec, lane = adjusted_node(30 - path_value)
                lane_ref = self._lane_tpl(vec, lane)
                if direct_node_lanes:
                    r4_t8_nodes.append(lane_ref)
                    r4_t8_node_reads_list.append(self._dep(vec))
                else:
                    scalar = self._reserve()
                    self._emit(
                        "salu", [self._dep(vec)], [("p", scalar)],
                        lane_slots=[("|", scalar, lane_ref, lane_ref)],
                    )
                    r4_t8_nodes.append(scalar)
            r4_t8_node_reads = (
                tuple(dict.fromkeys(r4_t8_node_reads_list))
                if direct_node_lanes else None
            )
            r4_t8_shift4 = self._const(4)
            r4_t8_shift8 = self._const(8)

        d3_cold_nodes = None
        d3_cold_node_reads = None
        if control_carry_mask or prepare_final_mask:
            direct_node_lanes = (
                os.getenv("TRANSFER_COLD_DIRECT_NODE_LANES", "0") != "0"
            )
            d3_cold_nodes = []
            d3_reads = []
            for path_value in range(8):
                vec, lane = adjusted_node(14 - path_value)
                lane_ref = self._lane_tpl(vec, lane)
                if direct_node_lanes:
                    d3_cold_nodes.append(lane_ref)
                    d3_reads.append(self._dep(vec))
                else:
                    scalar = self._reserve()
                    self._emit(
                        "salu", [self._dep(vec)], [("p", scalar)],
                        lane_slots=[("|", scalar, lane_ref, lane_ref)],
                    )
                    d3_cold_nodes.append(scalar)
            d3_cold_node_reads = tuple(dict.fromkeys(d3_reads)) if d3_reads else None

        depth_store_ids: dict[int, set[int]] = defaultdict(set)
        final_d4_shadow_store_ids: set[int] = set()
        eight_scalar = self._const(VLEN)
        destination_addr: dict[int, int] = {}
        previous = None
        for depth in range(3, 8):
            for block in range(1 << (depth - 3)):
                physical = (1 << depth) + 2 + VLEN * block
                if previous is None:
                    addr = self._constants[physical & 0xFFFFFFFF]
                else:
                    addr = self._reserve()
                    self._emit(
                        "salu", [("p", previous), ("p", eight_scalar)],
                        [("p", addr)],
