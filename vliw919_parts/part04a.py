                        state = control_carry_state.get(group)
                        if state is None or r - 1 not in bits:
                            raise RuntimeError(f"missing control-carry state g={group} r={r} state={state is not None} bits={sorted(bits)}")
                        source_targets, source_chain = state
                        mixed = self._cold_final_from_control(
                            current, bits[r - 1], source_targets, r4_t8_nodes,
                            workspace=cold_t8_workspace[group % cold_t8_pool_size],
                            node_reads=r4_t8_node_reads,
                            source_dispatch=source_chain["dispatch"],
                        )
                    else:
                        source_at_r14 = control_source or prepare_source
                        cold_nodes = d3_cold_nodes if source_at_r14 else r4_t8_nodes
                        cold_reads = d3_cold_node_reads if source_at_r14 else r4_t8_node_reads
                        if cold_nodes is None:
                            raise RuntimeError("cold node bank not initialized")
                        use_r14_q332 = (
                            source_at_r14
                            and ((int(os.getenv(
                                "TRANSFER_PREP_Q332_MASK", "0"
                            ), 0) >> group) & 1) != 0
                        )
                        source_workspace = (
                            tuple(self._reserve() for _ in range(
                                5 if use_r14_q332 else 4
                            ))
                            if source_at_r14
                            else cold_t8_workspace[group % cold_t8_pool_size]
                        )
                        prepared_pair_vectors = None
                        if prepare_source:
                            prepared_pair_vectors = (
                                self._new_vref(), self._new_vref()
                            )
                        mixed = self._cold_t8_lookup(
                            current, address, cold_nodes,
                            r4_t8_shift4, r4_t8_shift8,
                            workspace=source_workspace,
                            digit_bias=(
                                0 if (source_at_r14
                                      and (((r14_special_code_mask |
                                             r14_two_select_mask) >> group) & 1))
                                else (1 << 3) + 2 if source_at_r14
                                else 0 if final_d4_shadow and r == rounds - 1
                                else (1 << 4) + 2
                            ),
                            chunks_override=(
                                ((3, 3, 2) if use_r14_q332 else (4, 4))
                                if source_at_r14 else
                                (2, 2, 2, 2)
                                if ((r == 4 and ((r4_p4_mask >> group) & 1) != 0)
                                    or (r == rounds - 1
                                        and ((r15_p4_mask >> group) & 1) != 0))
                                else (4, 4)
                                if (r == rounds - 1
                                    and os.getenv("TRANSFER_R15_Q44", "0") != "0")
                                or (r == 4 and ((r4_q44_mask >> group) & 1) != 0)
                                else None
                            ),
                            force_flow_bases=(
                                (r == 4 and ((int(os.getenv(
                                    "TRANSFER_COLD_FLOW_BASE_R4_MASK", "0"), 0)
                                    >> group) & 1) != 0)
                                or (r == rounds - 1 and ((int(os.getenv(
                                    "TRANSFER_COLD_FLOW_BASE_R15_MASK", "0"), 0)
                                    >> group) & 1) != 0)
                            ),
                            node_reads=cold_reads,
                            prepare_pair_vectors=prepared_pair_vectors,
                            prepare_node_scalars=(
                                r4_t8_nodes if prepare_source else None
                            ),
                            prepare_node_reads=(
                                r4_t8_node_reads if prepare_source else None
                            ),
                            digit_map=(
                                ({0: 0, 1: 1, 9: 2, 10: 3,
                                  2: 4, 3: 5, 11: 6, 12: 7}
                                 if ((r14_two_select_mask >> group) & 1)
                                 else {1: 0, 2: 1, 9: 2, 10: 3,
                                       3: 4, 4: 5, 11: 6, 12: 7})
                                if (source_at_r14
                                    and (((r14_special_code_mask |
                                           r14_two_select_mask) >> group) & 1))
                                else None
                            ),
                        )
                        if prepare_source:
                            prepared_final_state[group] = prepared_pair_vectors
                        if control_source:
                            source_chain = self._r4_q8_chains[-1]
                            one_shift = self._cold_synth_scalar(1)
                            for target in source_chain["targets"]:
                                previous_writer = self._last_def.get(("p", target))
                                node = self._emit(
                                    "salu", [("p", target), ("p", one_shift)],
                                    [("p", target)],
                                    lane_slots=[("<<", target, target, one_shift)],
                                )
                                if previous_writer is not None:
                                    node.deps.add(previous_writer)
                            source_chain["control_source"] = True
                            control_carry_state[group] = (
                                tuple(source_chain["targets"]), source_chain
                            )
                elif mode == "gather":
                    fetched = self._gather(address)
                    gather_nodes = self.nodes[-VLEN:]
                    if depth in reverse_depths:
                        gather_store_ids = (
                            final_d4_shadow_store_ids
                            if final_d4_shadow and r == rounds - 1 and depth == 4
                            else depth_store_ids[depth]
                        )
                        for node in gather_nodes:
                            node.deps.update(gather_store_ids)
                        if final_d4_shadow and r == 3 and depth == 3:
                            blockers = {node.idx for node in gather_nodes}
                            for shadow_id in final_d4_shadow_store_ids:
                                self.nodes[shadow_id].deps.update(blockers)
                        mixed = self._vector_flex("^", current, fetched)
                    else:
                        mixed = self._vector_flex(
                            "^", current,
                            self._vector_flex("^", fetched, vc["c6"],
                                              scalar_b=sc["c6"]),
                        )
                else:
                    order = bit_places(depth)
                    first_cond = bits[r - order[0].bit_length()]
                    table = {}
                    for pair_index, offset in enumerate(row_offsets(depth)):
                        delta, left, right = blend_pairs[(depth, pair_index)]
                        if (delta is None
                                or (r == rounds - 1 and is_final_blend(group)
                                    and not v15_mflex)):
                            table[offset] = self._select(first_cond, left, right)
                        else:
                            table[offset] = self._pair_choice(
                                first_cond, delta, left, right,
                            )
                    xor_before_root = (
                        r >= 13 and depth >= 2
                        and (
                            ((nxw_mask >> group) & 1) != 0
                            or (nxw_groups > 0 and group >= groups - nxw_groups)
                        )
                    )
                    reduce_places = order[1:-1] if xor_before_root else order[1:]
                    for place in reduce_places:
                        cond = bits[r - place.bit_length()]
                        table = {
                            offset: self._select(cond, table[offset], table[offset | place])
                            for offset in table if not (offset & place)
                        }
                    if xor_before_root:
                        mixed = self._select(
                            bits[r - 1],
                            self._vector_flex("^", current, table[0]),
                            self._vector_flex("^", current, table[1]),
                        )
                    else:
                        mixed = self._vector_flex("^", current, table[0])

                fasttail = (
                    r == rounds - 2 and depth == 3
                    and needs_address(r + 1, group)
                    and ((fasttail_mask >> group) & 1) != 0
                )
                hash_result = self._hash(
                    mixed, vc, sc, final=(r == rounds - 1),
                    capture_tail=fasttail,
                )
                if fasttail:
                    current, fasttail_source, fasttail_shifted = hash_result
                else:
                    current = hash_result
                    fasttail_source = fasttail_shifted = None

                if r + 1 >= rounds or (r + 1) % level_count == 0:
                    continue
                next_depth = (r + 1) % level_count
                current_gather = mode in ("gather", "cold")
                next_needs = needs_address(r + 1, group)
                horizon_end = min(r - depth + level_count, rounds)
                later_needs = any(
                    needs_address(rr, group) for rr in range(r + 1, horizon_end)
                )

                if (current_gather and depth in reverse_depths and depth < 7
                        and needs_address(r + 1, group)
                        and next_depth in reverse_depths
