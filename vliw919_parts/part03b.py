                        lane_slots=[("+", addr, previous, eight_scalar)],
                    )
                destination_addr[physical] = addr
                previous = addr

        previous_source = raw_addresses[23]
        previous_offset = 23
        for depth in range(3, 8):
            transformed = []
            level_loads: list[int] = []
            for block in range(1 << (depth - 3)):
                offset = (1 << depth) - 1 + VLEN * block
                if offset in (7, 15, 23):
                    vec = adjusted[{7: 1, 15: 2, 23: 3}[offset]]
                else:
                    if offset == previous_offset + VLEN:
                        addr = self._reserve()
                        self._emit(
                            "salu", [("p", previous_source), ("p", eight_scalar)],
                            [("p", addr)],
                            lane_slots=[("+", addr, previous_source, eight_scalar)],
                        )
                    else:
                        addr = self._const(tree_base + offset)
                    previous_source, previous_offset = addr, offset
                    loaded = self._new_vref()
                    node = self._emit(
                        "load", [("p", addr)], [("v", loaded[1])],
                        load_slot=("vload", self._tpl(loaded), addr),
                    )
                    level_loads.append(node.idx)
                    vec = reverse_and_adjust(loaded)
                transformed.append(vec)

            for block, vec in enumerate(reversed(transformed)):
                addr = destination_addr[(1 << depth) + 2 + VLEN * block]
                store = self._emit(
                    "store", [("p", addr), self._dep(vec)], [],
                    store_slot=("vstore", addr, self._tpl(vec)),
                )
                store.deps.update(raw_load_ids)
                store.deps.update(level_loads)
                depth_store_ids[depth].add(store.idx)
                if final_d4_shadow and depth == 4:
                    shadow_addr = self._const(VLEN * block)
                    shadow = self._emit(
                        "store", [("p", shadow_addr), self._dep(vec)], [],
                        store_slot=("vstore", shadow_addr, self._tpl(vec)),
                    )
                    shadow.deps.update(raw_load_ids)
                    shadow.deps.update(level_loads)
                    stage_bank0 = getattr(self, "_node_stage_banks", {}).get(0)
                    if stage_bank0 is not None and stage_bank0["last_load"] is not None:
                        shadow.deps.add(stage_bank0["last_load"])
                    final_d4_shadow_store_ids.add(shadow.idx)

        root_native = self._broadcast_lane_temp(raw_vecs[0], 0)
        root_adjusted = self._broadcast_lane_fixed(adjusted[0], 0)

        def bit_places(depth: int) -> list[int]:
            return [1 << bit for bit in range(depth - 1, 0, -1)] + [1]

        def row_offsets(depth: int) -> list[int]:
            first = bit_places(depth)[0]
            return [x for x in range(1 << depth) if not (x & first)]

        blend_depths = {
            r % level_count
            for r in range(rounds)
            for group in range(groups)
            if path_mode(r, group) == "blend"
        }
        pure_flow_pair_masks = {
            depth: int(os.getenv(
                f"TRANSFER_PURE_FLOW_PAIR_MASK_D{depth}", "0"
            ), 0)
            for depth in range(1, max(blend_depths, default=0) + 1)
        }
        blend_pairs: dict[tuple[int, int], tuple] = {}
        for depth in range(1, max(blend_depths) + 1):
            order = bit_places(depth)
            offs = row_offsets(depth)
            for pair_index in range(1 << (depth - 1)):
                left_index = (1 << depth) - 1 + offs[pair_index]
                right_index = left_index + order[0]
                lv, llane = adjusted_node(left_index)
                rv, rlane = adjusted_node(right_index)
                pure_flow = (
                    ((pure_flow_pair_masks.get(depth, 0) >> pair_index) & 1) != 0
                )
                if depth == 4:
                    left = self._broadcast_lane_temp(lv, llane)
                    right = self._broadcast_lane_temp(rv, rlane)
                    delta = None if pure_flow else self._vector_flex("-", left, right)
                else:
                    left = self._broadcast_lane_fixed(lv, llane)
                    right = self._broadcast_lane_fixed(rv, rlane)
                    if pure_flow:
                        delta = None
                    else:
                        delta = self._reserve(VLEN)
                        self._emit(
                            "flex", [("p", left), ("p", right)], [("p", delta)],
                            vector_slot=("-", delta, left, right),
                            lane_slots=[("-", delta + k, left + k, right + k)
                                        for k in range(VLEN)],
                        )
                blend_pairs[(depth, pair_index)] = (delta, left, right)

        group_first: dict[int, int] = {}
        group_second: dict[int, int] = {}
        control_carry_state: dict[int, tuple[tuple[int, ...], dict]] = {}
        prepared_final_state: dict[int, tuple[object, object]] = {}
        input_loads: dict[int, int] = {}
        input_addr: dict[int, int] = {}

        for group in range(groups):
            self._active_group = group
            self._active_round = -1
            group_first[group] = len(self.nodes)
            if group == 0:
                input_addr[group] = self._const(values_base)
            else:
                addr = self._reserve()
                self._emit(
                    "salu", [("p", input_addr[group - 1]), ("p", eight_scalar)],
                    [("p", addr)],
                    lane_slots=[("+", addr, input_addr[group - 1], eight_scalar)],
                )
                input_addr[group] = addr

            current = self._new_vref()
            input_loads[group] = self._emit(
                "load", [("p", input_addr[group])], [("v", current[1])],
                load_slot=("vload", self._tpl(current), input_addr[group]),
            ).idx

            path_acc = None
            bits: dict[int, object] = {}
            address = None
            use_pfold = (
                not is_final_blend(group)
                and (
                    ((pfold_mask >> group) & 1) != 0
                    or (pfold_groups > 0
                        and group >= groups - final_blend_groups - pfold_groups)
                )
            )

            for r in range(rounds):
                self._active_round = r
                depth = r % level_count
                mode = path_mode(r, group)
                if r == 0:
                    mixed = self._vector_flex("^", current, root_native)
                elif depth == 0:
                    group_second[group] = len(self.nodes)
                    mixed = self._vector_flex("^", current, root_adjusted)
                elif mode == "prepared":
                    state = prepared_final_state.get(group)
                    if state is None or r - 1 not in bits:
                        raise RuntimeError(
                            f"missing prepared-final state g={group} r={r}"
                        )
                    yes_nodes, no_nodes = state
                    if ((prepare_xor_before_select_mask >> group) & 1) != 0:
                        yes_mixed = self._vector_flex("^", current, yes_nodes)
                        no_mixed = self._vector_flex("^", current, no_nodes)
                        mixed = self._select(bits[r - 1], yes_mixed, no_mixed)
                    else:
                        selected = self._select(bits[r - 1], yes_nodes, no_nodes)
                        mixed = self._vector_flex("^", current, selected)
                elif mode == "cold":
                    prepare_source = (
                        r == rounds - 2 and depth == 3
                        and ((prepare_final_mask >> group) & 1) != 0
                    )
                    control_source = (
                        r == rounds - 2 and depth == 3
                        and ((control_carry_mask >> group) & 1) != 0
                    )
                    control_final = (
                        r == rounds - 1 and depth == 4
                        and ((control_carry_mask >> group) & 1) != 0
                    )
                    if (r4_t8_shift4 is None or r4_t8_shift8 is None
                            or (address is None and not control_final)):
                        raise RuntimeError("cold path/table not initialized")
                    if control_final:
