        dest = self._new_vref()
        scalar_tpl = self._lane_tpl(src, lane)
        lane_slots = [
            ("|", self._lane_tpl(dest, k), scalar_tpl, scalar_tpl)
            for k in range(VLEN)
        ]
        self._emit(
            "flex", [self._dep(src)], [("v", dest[1])],
            vector_slot=("vbroadcast", self._tpl(dest), scalar_tpl),
            lane_slots=lane_slots,
        )
        return dest

    def _madd(self, a, b, c):
        dest = self._new_vref()
        self._emit(
            "valu", [self._dep(a), self._dep(b), self._dep(c)],
            [("v", dest[1])],
            vector_slot=("multiply_add", self._tpl(dest), self._tpl(a),
                         self._tpl(b), self._tpl(c)),
        )
        return dest

    def _select(self, cond, yes, no):
        dest = self._new_vref()
        self._emit(
            "flow_only", [self._dep(cond), self._dep(yes), self._dep(no)],
            [("v", dest[1])],
            flow_slot=("vselect", self._tpl(dest), self._tpl(cond),
                       self._tpl(yes), self._tpl(no)),
        )
        return dest

    def _pair_choice(self, cond, delta, left, right):
        if left is None:
            return self._madd(cond, delta, right)
        dest = self._new_vref()
        self._emit(
            "mix_flex",
            [self._dep(cond), self._dep(delta), self._dep(left), self._dep(right)],
            [("v", dest[1])],
            vector_slot=("multiply_add", self._tpl(dest), self._tpl(cond),
                         self._tpl(delta), self._tpl(right)),
            flow_slot=("vselect", self._tpl(dest), self._tpl(cond),
                       self._tpl(left), self._tpl(right)),
        )
        return dest

    def _vector_flex(self, opcode: str, a, b, *, scalar_b: int | None = None):
        dest = self._new_vref()
        reads = [self._dep(a), self._dep(b)]
        if scalar_b is not None:
            reads.append(("p", scalar_b))
        lane_slots = [
            (
                opcode,
                self._lane_tpl(dest, k),
                self._lane_tpl(a, k),
                scalar_b if scalar_b is not None else self._lane_tpl(b, k),
            )
            for k in range(VLEN)
        ]
        self._emit(
            "flex", reads, [("v", dest[1])],
            vector_slot=(opcode, self._tpl(dest), self._tpl(a), self._tpl(b)),
            lane_slots=lane_slots,
        )
        return dest

    def _lane_vector(self, opcode: str, a, b):
        dest = self._new_vref()

        def operand(o, lane: int):
            return o[1] if isinstance(o, tuple) and o[0] == "scalar" else self._lane_tpl(o, lane)

        reads = [
            ("p", o[1]) if isinstance(o, tuple) and o[0] == "scalar" else self._dep(o)
            for o in (a, b)
        ]
        slots = [
            (opcode, self._lane_tpl(dest, k), operand(a, k), operand(b, k))
            for k in range(VLEN)
        ]
        self._emit("alu8", reads, [("v", dest[1])], lane_slots=slots)
        return dest

    def _gather(self, address):
        dest = self._new_vref()
        for lane in range(VLEN):
            self._emit(
                "load", [self._dep(address)], [("vl", dest[1], lane)],
                load_slot=("load_offset", self._tpl(dest),
                           self._tpl(address), lane),
            )
        return dest

    def _cold_synth_scalar(self, value: int) -> int:
        value &= 0xFFFFFFFF
        existing = self._constants.get(value)
        if existing is not None:
            return existing
        cached = self._cold_synth_scalars.get(value)
        if cached is not None:
            return cached

        expr = {
            3: ("+", 1, 2),
            6: ("+", 2, 4),
            12: ("+", 4, 8),
            15: ("-", 16, 1),
            256: ("<<", 1, 8),
            4096: ("-", 4097, 1),
            4352: ("+", 4096, 256),
            4368: ("+", 4352, 16),
            4369: ("+", 4368, 1),
            8192: ("+", 4096, 4096),
            61440: ("*", 4096, 15),
            65536: ("<<", 1, 16),
            78642: ("*", 4369, 18),
            122880: ("+", 61440, 61440),
            126414: ("-", 205056, 78642),
            187854: ("+", 126414, 61440),
            196608: ("*", 65536, 3),
            204800: ("+", 196608, 8192),
            205056: ("+", 204800, 256),
            249294: ("+", 126414, 122880),
            283698: ("+", 205056, 78642),
            314830: ("+", 249294, 65536),
            314574: ("-", 314830, 256),
            348978: ("-", 471858, 122880),
            393216: ("*", 65536, 6),
            410418: ("-", 471858, 61440),
            471858: ("+", 393216, 78642),
        }
        spec = expr.get(value)
        if spec is None:
            fallback_values = (466944, 405504, 348672, 131328, 192768, 249600)
            fallback_index = (
                fallback_values.index(value) if value in fallback_values else -1
            )
            fallback_flow_mask = int(
                os.getenv("TRANSFER_COLD_FALLBACK_FLOW_MASK", "0"), 0
            )
            via_flow = (
                os.getenv("TRANSFER_COLD_FALLBACK_FLOW", "0") != "0"
                or (fallback_index >= 0
                    and ((fallback_flow_mask >> fallback_index) & 1) != 0)
            )
            return self._const(value, via_flow=via_flow)
        opcode, left_value, right_value = spec
        left = self._cold_synth_scalar(left_value)
        right = self._cold_synth_scalar(right_value)
        cell = self._reserve()
        self._emit(
            "salu", [("p", left), ("p", right)], [("p", cell)],
            lane_slots=[(opcode, cell, left, right)],
        )
        self._cold_synth_scalars[value] = cell
        return cell

    def _cold_absolute_base(self, chunk: int, stage_bias: int) -> int:
        chains = max(1, int(os.getenv("TRANSFER_COLD_BASE_CHAINS", "1")))
        chain = self._cold_stage_index % chains
        relative = self._cold_table_cursor - stage_bias
        state = self._cold_base_chain_state.get(chain)
        if state is None:
            share_roots = os.getenv("TRANSFER_COLD_ROOT_SHARE", "0") != "0"
            if (share_roots and chain > 0
                    and self._cold_shared_root_cell is not None
                    and relative == self._cold_shared_root_relative + chain * 65536
                    and chain - 1 in self._cold_root_cells):
                previous = self._cold_root_cells[chain - 1]
                unit = self._cold_synth_scalar(65536)
                cell = self._reserve()
                self._emit(
                    "salu", [("p", previous), ("p", unit)], [("p", cell)],
                    lane_slots=[("+", cell, previous, unit)],
                )
            else:
                cell = self._reserve()
                marker = (0x6C0D0000 + chain) & 0xFFFFFFFF
                node = self._emit(
                    "load", [], [("p", cell)],
                    load_slot=("const", cell, marker),
                )
                self._cold_base_roots.append((node.idx, cell, relative))
                if share_roots and chain == 0:
                    self._cold_shared_root_cell = cell
                    self._cold_shared_root_relative = relative
            self._cold_root_cells[chain] = cell
        else:
            previous_cell, previous_relative = state
            increment = (relative - previous_relative) & 0xFFFFFFFF
            synth_all = os.getenv("TRANSFER_COLD_SYNTH_ALL", "0") != "0"
            synth_common = os.getenv("TRANSFER_COLD_SYNTH_COMMON", "0") != "0"
            inc = (self._cold_synth_scalar(increment)
                   if synth_all or (synth_common and increment == 393216)
                   else self._const(increment))
            cell = self._reserve()
            self._emit(
                "salu", [("p", previous_cell), ("p", inc)],
                [("p", cell)],
                lane_slots=[("+", cell, previous_cell, inc)],
            )
        self._cold_base_chain_state[chain] = (cell, relative)
        self._cold_table_cursor += 16 ** chunk
        self._cold_stage_index += 1
        return cell

    def _cold_t8_lookup(self, current, path, node_scalars,
                        shift4_scalar: int, shift8_scalar: int,
                        workspace: tuple[int, ...] | None = None,
                        digit_bias: int = 0,
                        chunks_override: tuple[int, ...] | None = None,
                        force_flow_bases: bool = False,
                        node_reads: tuple[tuple, ...] | None = None,
                        prepare_pair_vectors: tuple[object, object] | None = None,
                        prepare_node_scalars: tuple | list | None = None,
                        prepare_node_reads: tuple[tuple, ...] | None = None,
                        digit_map: dict[int, int] | None = None):
        chunks = chunks_override or (3, 3, 2)
        stage_bias_values = tuple(
            digit_bias * ((16 ** chunk - 1) // 15) for chunk in chunks
        )
        alu_absolute_bases = (
            os.getenv("TRANSFER_COLD_BASE_ALU", "0") != "0"
            and not force_flow_bases
        )
        targets: list[int] = []
        add_nodes: list[int] = []
        lane0 = 0
        workspace_at = 0
        balanced_pack = os.getenv("TRANSFER_COLD_PACK_BALANCED", "0") != "0"
        shift12_scalar = self._cold_synth_scalar(12) if balanced_pack else None
        for chunk in chunks:
            extra_temp = None
            if workspace is None:
                target = self._reserve()
                temp = self._reserve() if chunk in (3, 4) else None
                if chunk == 4 and balanced_pack:
                    extra_temp = self._reserve()
            else:
                target = workspace[workspace_at]
                workspace_at += 1
                temp = None
                if chunk in (3, 4):
                    temp = workspace[workspace_at]
                    workspace_at += 1
                if chunk == 4 and balanced_pack:
                    extra_temp = workspace[workspace_at]
                    workspace_at += 1
            if chunk == 4 and balanced_pack:
                self._emit(
                    "salu", [self._dep(path), ("p", shift12_scalar)],
                    [("p", target)],
                    lane_slots=[("<<", target, self._lane_tpl(path, lane0),
                                 shift12_scalar)],
                )
                self._emit(
                    "salu", [self._dep(path), ("p", shift8_scalar)],
                    [("p", temp)],
                    lane_slots=[("<<", temp, self._lane_tpl(path, lane0 + 1),
                                 shift8_scalar)],
                )
                self._emit(
                    "salu", [self._dep(path), ("p", shift4_scalar)],
                    [("p", extra_temp)],
                    lane_slots=[("<<", extra_temp,
                                 self._lane_tpl(path, lane0 + 2),
                                 shift4_scalar)],
                )
                self._emit(
                    "salu", [("p", target), ("p", temp)],
                    [("p", target)],
                    lane_slots=[("+", target, target, temp)],
                )
                self._emit(
                    "salu", [("p", extra_temp), self._dep(path)],
                    [("p", extra_temp)],
                    lane_slots=[("+", extra_temp, extra_temp,
                                 self._lane_tpl(path, lane0 + 3))],
                )
                self._emit(
                    "salu", [("p", target), ("p", extra_temp)],
                    [("p", target)],
                    lane_slots=[("+", target, target, extra_temp)],
                )
            elif chunk == 4:
                self._emit(
                    "salu", [self._dep(path), ("p", shift4_scalar)],
                    [("p", target)],
                    lane_slots=[("<<", target, self._lane_tpl(path, lane0),
                                 shift4_scalar)],
                )
                self._emit(
                    "salu", [("p", target), self._dep(path)], [("p", target)],
                    lane_slots=[("+", target, target,
                                 self._lane_tpl(path, lane0 + 1))],
                )
                self._emit(
                    "salu", [self._dep(path), ("p", shift4_scalar)],
                    [("p", temp)],
                    lane_slots=[("<<", temp, self._lane_tpl(path, lane0 + 2),
                                 shift4_scalar)],
                )
                self._emit(
                    "salu", [("p", temp), self._dep(path)], [("p", temp)],
                    lane_slots=[("+", temp, temp,
                                 self._lane_tpl(path, lane0 + 3))],
                )
                self._emit(
                    "salu", [("p", target), ("p", shift8_scalar)],
                    [("p", target)],
                    lane_slots=[("<<", target, target, shift8_scalar)],
                )
                self._emit(
                    "salu", [("p", target), ("p", temp)],
                    [("p", target), ("p", temp)],
                    lane_slots=[("+", target, target, temp)],
                )
            elif chunk == 3:
                self._emit(
                    "salu", [self._dep(path), ("p", shift8_scalar)],
                    [("p", target)],
                    lane_slots=[("<<", target, self._lane_tpl(path, lane0),
                                 shift8_scalar)],
                )
                self._emit(
                    "salu", [self._dep(path), ("p", shift4_scalar)],
                    [("p", temp)],
                    lane_slots=[("<<", temp, self._lane_tpl(path, lane0 + 1),
                                 shift4_scalar)],
                )
                self._emit(
                    "salu", [("p", temp), self._dep(path)], [("p", temp)],
                    lane_slots=[("+", temp, temp,
                                 self._lane_tpl(path, lane0 + 2))],
                )
                self._emit(
                    "salu", [("p", target), ("p", temp)],
                    [("p", target), ("p", temp)],
                    lane_slots=[("+", target, target, temp)],
                )
            elif chunk == 2:
                self._emit(
                    "salu", [self._dep(path), ("p", shift4_scalar)],
                    [("p", target)],
                    lane_slots=[("<<", target, self._lane_tpl(path, lane0),
                                 shift4_scalar)],
                )
                self._emit(
                    "salu", [("p", target), self._dep(path)], [("p", target)],
                    lane_slots=[("+", target, target,
                                 self._lane_tpl(path, lane0 + 1))],
                )
            else:
                raise RuntimeError(f"unsupported cold chunk {chunk}")
            if alu_absolute_bases:
                base_cell = self._cold_absolute_base(
                    chunk, stage_bias_values[len(targets)]
                )
                add = self._emit(
                    "salu", [("p", target), ("p", base_cell)],
                    [("p", target)],
                    lane_slots=[("+", target, target, base_cell)],
                )
            else:
                add = self._emit(
                    "flow_only", [("p", target)], [("p", target)],
                    flow_slot=("add_imm", target, target, 0),
                )
                self._cold_table_cursor += 16 ** chunk
                self._cold_stage_index += 1
            targets.append(target)
            add_nodes.append(add.idx)
            lane0 += chunk

        head_reads = [("p", target) for target in targets]
        if node_reads is None:
            head_reads.extend(("p", node) for node in node_scalars)
        else:
