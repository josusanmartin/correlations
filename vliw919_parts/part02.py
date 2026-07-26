            head_reads.extend(node_reads)
        if prepare_pair_vectors is not None:
            if prepare_node_scalars is None:
                raise RuntimeError("prepared pairs require a depth-4 node bank")
            if prepare_node_reads is None:
                head_reads.extend(("p", node) for node in prepare_node_scalars)
            else:
                head_reads.extend(prepare_node_reads)
        head_reads.append(self._dep(current))

        placeholders = []
        lane_cursor = 0
        stage_alu_counts = []
        for chunk in chunks:
            stage_slots = [
                ("^", self._lane_tpl(current, lane_cursor + j),
                 self._lane_tpl(current, lane_cursor + j), node_scalars[0])
                for j in range(chunk)
            ]
            if prepare_pair_vectors is not None:
                yes_vec, no_vec = prepare_pair_vectors
                stage_slots.extend(
                    ("|", self._lane_tpl(yes_vec, lane_cursor + j),
                     prepare_node_scalars[1], prepare_node_scalars[1])
                    for j in range(chunk)
                )
                stage_slots.extend(
                    ("|", self._lane_tpl(no_vec, lane_cursor + j),
                     prepare_node_scalars[0], prepare_node_scalars[0])
                    for j in range(chunk)
                )
            placeholders.extend(stage_slots)
            stage_alu_counts.append(len(stage_slots))
            lane_cursor += chunk

        dispatch_writes = [("v", current[1])]
        if workspace is not None:
            dispatch_writes.extend(("p", target) for target in targets)
        if prepare_pair_vectors is not None:
            dispatch_writes.extend(("v", vec[1]) for vec in prepare_pair_vectors)
        dispatch = self._emit(
            "cold_dispatch", head_reads, dispatch_writes,
            flow_slot=("jump_indirect", targets[0]), lane_slots=placeholders,
        )
        self._r4_q8_chains.append({
            "targets": tuple(targets), "add_nodes": tuple(add_nodes),
            "dispatch": dispatch.idx, "current": current[1],
            "nodes": tuple(node_scalars), "chunks": tuple(chunks),
            "stage_biases": stage_bias_values,
            "absolute_bases": alu_absolute_bases,
            "stage_alu_counts": tuple(stage_alu_counts),
            "prepare_pairs": prepare_pair_vectors is not None,
            "prepare_pair_vectors": (
                tuple(vec[1] for vec in prepare_pair_vectors)
                if prepare_pair_vectors is not None else None
            ),
            "prepare_node_scalars": (
                tuple(prepare_node_scalars)
                if prepare_node_scalars is not None else None
            ),
            "digit_map": dict(digit_map) if digit_map is not None else None,
        })
        self._cold_dispatch_latency[dispatch.idx] = 1 + len(chunks)
        return current

    def _cold_final_from_control(
        self, current, newest_bit, source_targets, node_scalars,
        workspace: tuple[int, ...] | None = None,
        node_reads: tuple[tuple, ...] | None = None,
        source_dispatch: int | None = None,
    ):
        """Final depth-4 cold lookup from scaled round-14 table targets."""
        if source_dispatch is None:
            raise RuntimeError("control carry needs its source dispatch")
        if self._control_carry_k_cell is None:
            cell = self._reserve()
            marker_value = 0x6C0DCA77
            node = self._emit(
                "load", [], [("p", cell)],
                load_slot=("const", cell, marker_value),
            )
            self._control_carry_k_cell = cell
            self._control_carry_k_node = node.idx
        k_cell = self._control_carry_k_cell
        chunks = (4, 4)
        shift4 = self._cold_synth_scalar(4)
        shift8 = self._cold_synth_scalar(8)
        targets = []
        lane0 = 0
        for stage, chunk in enumerate(chunks):
            if workspace is None:
                target, temp = self._reserve(), self._reserve()
            else:
                target = workspace[2 * stage]
                temp = workspace[2 * stage + 1]
            previous_target_writer = self._last_def.get(("p", target))
            first_pack = len(self.nodes)
            self._emit(
                "salu", [self._dep(newest_bit), ("p", shift4)], [("p", target)],
                lane_slots=[("<<", target, self._lane_tpl(newest_bit, lane0), shift4)],
            )
            self._emit(
                "salu", [("p", target), self._dep(newest_bit)], [("p", target)],
                lane_slots=[("+", target, target, self._lane_tpl(newest_bit, lane0 + 1))],
            )
            self._emit(
                "salu", [self._dep(newest_bit), ("p", shift4)], [("p", temp)],
                lane_slots=[("<<", temp, self._lane_tpl(newest_bit, lane0 + 2), shift4)],
            )
            self._emit(
                "salu", [("p", temp), self._dep(newest_bit)], [("p", temp)],
                lane_slots=[("+", temp, temp, self._lane_tpl(newest_bit, lane0 + 3))],
            )
            self._emit(
                "salu", [("p", target), ("p", shift8)], [("p", target)],
                lane_slots=[("<<", target, target, shift8)],
            )
            self._emit(
                "salu", [("p", target), ("p", temp)], [("p", target), ("p", temp)],
                lane_slots=[("+", target, target, temp)],
            )
            self._emit(
                "salu", [("p", target), ("p", source_targets[stage])], [("p", target)],
                lane_slots=[("+", target, target, source_targets[stage])],
            )
            self._emit(
                "salu", [("p", target), ("p", k_cell)], [("p", target)],
                lane_slots=[("+", target, target, k_cell)],
            )
            if previous_target_writer is not None:
                self.nodes[first_pack].deps.add(previous_target_writer)
            targets.append(target)
            lane0 += chunk

        head_reads = [("p", target) for target in targets]
        head_reads.extend(("p", target) for target in source_targets)
        head_reads.append(("p", k_cell))
        if node_reads is None:
            head_reads.extend(("p", node) for node in node_scalars)
        else:
            head_reads.extend(node_reads)
        head_reads.append(self._dep(current))
        placeholders = [
            ("^", self._lane_tpl(current, lane), self._lane_tpl(current, lane),
             node_scalars[0]) for lane in range(VLEN)
        ]
        dispatch_writes = [("v", current[1])]
        if workspace is not None:
            dispatch_writes.extend(("p", target) for target in targets)
        dispatch = self._emit(
            "cold_dispatch", head_reads, dispatch_writes,
            flow_slot=("jump_indirect", targets[0]), lane_slots=placeholders,
        )
        self._r4_q8_chains.append({
            "targets": tuple(targets), "add_nodes": (),
            "dispatch": dispatch.idx, "current": current[1],
            "nodes": tuple(node_scalars), "chunks": chunks,
            "stage_biases": (0, 0), "absolute_bases": True,
            "control_alias": True,
            "control_source_dispatch": source_dispatch,
        })
        self._cold_dispatch_latency[dispatch.idx] = 1 + len(chunks)
        return current

    def _hash(self, value, vector_constants, scalar_constants, *, final: bool,
              capture_tail: bool = False):
        x = self._madd(value, vector_constants["m0"], vector_constants["c0"])
        shifted = self._vector_flex(">>", x, vector_constants["s1"],
                                    scalar_b=scalar_constants["s1"])
        x = self._vector_flex(
            "^",
            self._vector_flex("^", x, vector_constants["c1"],
                              scalar_b=scalar_constants["c1"]),
            shifted,
        )
        left = self._madd(x, vector_constants["m2"], vector_constants["c23"])
        right = self._madd(x, vector_constants["m2s"], vector_constants["c2s"])
        x = self._madd(
            self._vector_flex("^", left, right),
            vector_constants["m4"], vector_constants["c4"],
        )
        tail_source = x
        shifted = self._vector_flex(">>", x, vector_constants["s5"],
                                    scalar_b=scalar_constants["s5"])
        if final:
            x = self._vector_flex("^", x, vector_constants["c6"],
                                  scalar_b=scalar_constants["c6"])
        result = self._vector_flex("^", x, shifted)
        if capture_tail:
            return result, tail_source, shifted
        return result

    def build(self, forest_height: int, n_nodes: int, batch_size: int, rounds: int) -> None:
        if batch_size % VLEN:
            raise ValueError("batch size must be vector aligned")
        tree_base = 7
        values_base = tree_base + n_nodes + batch_size
        level_count = forest_height + 1
        groups = batch_size // VLEN

        stages = HASH_STAGES
        c0, s0 = stages[0][1], stages[0][4]
        c1, s1 = stages[1][1], stages[1][4]
        c2, s2 = stages[2][1], stages[2][4]
        c3, s3 = stages[3][1], stages[3][4]
        c4, s4 = stages[4][1], stages[4][4]
        c5, s5 = stages[5][1], stages[5][4]
        self._node_stage_extra_base = values_base + batch_size
        self._fixed_lane_bcast_ordinal = 0
        self._staged_node_bcast_count = 0
        hvals = {
            "m0": (1 << s0) + 1,
            "c0": c0,
            "s1": s1,
            "c1": c1,
            "m2": (1 << s2) + 1,
            "c23": c2 + c3,
            "m2s": ((1 << s2) + 1) << s3,
            "c2s": c2 << s3,
            "m4": (1 << s4) + 1,
            "c4": c4,
            "s5": s5,
            "c6": c5,
        }
        hot = {"m0", "c0"}
        vc = {name: self._broadcast(val, flow_const=name not in hot)
              for name, val in hvals.items()}
        sc = {name: self._constants[val & 0xFFFFFFFF] for name, val in hvals.items()}

        one_scalar = self._const(1, via_flow=True)
        two_vec = self._broadcast(2, flow_const=True)
        one_vec = self._broadcast(1, flow_const=True)

        early_d3_groups = max(0, min(
            groups, int(os.getenv("TRANSFER_EARLY_D3_GROUPS", "2"))
        ))
        early_d4_groups = max(0, min(
            groups, int(os.getenv("TRANSFER_EARLY_D4_GROUPS", "4"))
        ))
        final_blend_groups = int(os.getenv("TRANSFER_FINAL_BLEND_GROUPS", "5"))
        blend_mask_raw = os.getenv("TRANSFER_FINAL_BLEND_MASK")
        final_blend_mask = (
            int(blend_mask_raw, 0) & ((1 << groups) - 1)
            if blend_mask_raw is not None
            else (((1 << final_blend_groups) - 1) << (groups - final_blend_groups))
        )
        final_blend_groups = final_blend_mask.bit_count()
        def is_final_blend(group: int) -> bool:
            return ((final_blend_mask >> group) & 1) != 0
        nxw_groups = max(0, min(int(os.getenv("TRANSFER_NXW", "0")), groups))
        nxw_mask_raw = os.getenv("TRANSFER_NXW_MASK")
        nxw_mask = (
            int(nxw_mask_raw, 0) & ((1 << groups) - 1)
            if nxw_mask_raw is not None else 0
        )
        v15_mflex = os.getenv("TRANSFER_V15_MFLEX", "1") != "0"
        fasttail_mask = int(os.getenv("TRANSFER_FASTTAIL_MASK", "0"), 0) & ((1 << groups) - 1)
        control_carry_mask = int(
            os.getenv("TRANSFER_R14_CONTROL_CARRY_MASK", "0"), 0
        ) & ((1 << groups) - 1)
        prepare_final_mask = int(
            os.getenv("TRANSFER_R14_PREP_FINAL_MASK", "0"), 0
        ) & ((1 << groups) - 1)
        prepare_xor_before_select_mask = int(
            os.getenv("TRANSFER_R15_PREP_XOR_BEFORE_SELECT_MASK", "0"), 0
        ) & prepare_final_mask
        prepare_final_mask &= ~control_carry_mask
        r4_t8_mask = int(os.getenv("TRANSFER_R4_T8_MASK", "0"), 0) & ((1 << groups) - 1)
        r4_q44_mask = int(os.getenv("TRANSFER_R4_Q44_MASK", "0"), 0) & r4_t8_mask
        r4_p4_mask = int(os.getenv("TRANSFER_R4_P4_MASK", "0"), 0) & r4_t8_mask
        r15_t8_mask = (int(os.getenv("TRANSFER_R15_T8_MASK", "0"), 0)
                         | control_carry_mask) & ((1 << groups) - 1)
        r15_t8_mask &= ~final_blend_mask
        r15_p4_mask = int(os.getenv("TRANSFER_R15_P4_MASK", "0"), 0) & r15_t8_mask
        pfold_groups = max(0, min(
            int(os.getenv("TRANSFER_PFOLD", "0")),
            groups - final_blend_groups,
        ))
        pfold_mask_raw = os.getenv("TRANSFER_PFOLD_MASK")
        pfold_mask = (
            int(pfold_mask_raw, 0) & ((1 << groups) - 1)
            if pfold_mask_raw is not None else 0
        )
        reverse_depths = {3, 4, 5, 6, 7}
        final_d4_shadow = os.getenv("TRANSFER_FINAL_D4_SHADOW", "0") != "0"

        active_r15_cold_mask = r15_t8_mask & ~prepare_final_mask
        cold_dispatch_count = (
            r4_t8_mask.bit_count()
            + active_r15_cold_mask.bit_count()
            + control_carry_mask.bit_count()
            + prepare_final_mask.bit_count()
        )
        cold_t8_pool_size = max(1, min(
            cold_dispatch_count or 1,
            int(os.getenv("TRANSFER_T8_POOL", "16")),
        ))
        cold_workspace_words = (
            6 if os.getenv("TRANSFER_COLD_PACK_BALANCED", "0") != "0" else 5
        )
        cold_t8_workspace = (
            [tuple(self._reserve() for _ in range(cold_workspace_words))
             for _ in range(cold_t8_pool_size)]
            if cold_dispatch_count else None
        )

        all_group_mask = (1 << groups) - 1
        r4_nonblend_mask = r4_t8_mask | ((1 << early_d4_groups) - 1)
        keep_dead_d5 = os.getenv("TRANSFER_KEEP_DEAD_D5", "0") != "0"
        reverse_entry_depths = (
            (3, 4, 5)
            if keep_dead_d5 or r4_nonblend_mask != all_group_mask
            else (3, 4)
        )
        reverse_entry_load_consts = (
            os.getenv("TRANSFER_REVERSE_ENTRY_LOAD_CONSTS", "0") != "0"
        )
        reverse_entry = {
            depth: self._broadcast(
                (1 << depth) + 2,
                flow_const=not reverse_entry_load_consts,
            )
            for depth in reverse_entry_depths
        }
        address_offset_select = (
            os.getenv("TRANSFER_ADDR_OFFSET_SELECT", "0") != "0"
        )
        address_offset_group_mask = int(
            os.getenv("TRANSFER_ADDR_OFFSET_GROUP_MASK", "0xffffffff"), 0
        ) & ((1 << groups) - 1)
        address_offset_depth_mask = int(
            os.getenv("TRANSFER_ADDR_OFFSET_DEPTH_MASK", "0x38"), 0
        )
        selected_offset_depths = tuple(
            depth for depth in reverse_entry_depths
            if address_offset_select and ((address_offset_depth_mask >> depth) & 1)
        )
        reverse_entry_plus1 = {}
        for depth in selected_offset_depths:
            if depth == 4 and os.getenv("TRANSFER_ALIAS_ENTRY4_PLUS1", "1") != "0":
                reverse_entry_plus1[depth] = vc["s1"]
            else:
                reverse_entry_plus1[depth] = self._vector_flex(
                    "+", reverse_entry[depth], one_vec
                )
        native_bias = self._broadcast(-(tree_base - 2), flow_const=True)
        neg_two_vec = self._broadcast(-2, flow_const=True)
        neg_two_scalar = self._constants[(-2) & 0xFFFFFFFF]
        native8 = self._broadcast(tree_base + 3 * (1 << 8) + 2,
                                  flow_const=True)
        native_offset_group_mask = int(
            os.getenv("TRANSFER_NATIVE_OFFSET_SELECT_MASK", "0"), 0
        ) & ((1 << groups) - 1)
        native_offset_round_mask = int(
            os.getenv("TRANSFER_NATIVE_OFFSET_ROUND_MASK", "0x380"), 0
        )
        native_site_masks = {
            rr: (
                int(os.environ[f"TRANSFER_NATIVE_OFFSET_MASK_R{rr}"], 0)
                & ((1 << groups) - 1)
                if f"TRANSFER_NATIVE_OFFSET_MASK_R{rr}" in os.environ
                else (native_offset_group_mask
                      if ((native_offset_round_mask >> rr) & 1) else 0)
            )
            for rr in (7, 8, 9)
        }
        def native_offset_selected(group: int, round_idx: int) -> bool:
            return ((native_site_masks.get(round_idx, 0) >> group) & 1) != 0

        if any(native_site_masks.values()):
            native8_minus1 = self._vector_flex("-", native8, one_vec)
            native_bias_minus1 = self._vector_flex("-", native_bias, one_vec)
        else:
            native8_minus1 = native_bias_minus1 = None
        tail2_flow_mask = int(
            os.getenv("TRANSFER_TAIL2_FLOW_MASK", "0"), 0
        ) & ((1 << groups) - 1)
        r14_tail2_mask = int(
            os.getenv("TRANSFER_R14_TAIL2_MASK", "0"), 0
