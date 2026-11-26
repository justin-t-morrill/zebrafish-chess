/* Production bitboard move generator and legality analysis. */

static bool bitboard_square_attacked_occ(const Position *p, int square,
                                         Color by_side, uint64_t occupied) {
    Color reverse_pawn = by_side == WHITE ? BLACK : WHITE;
    if (p->pieces[by_side][0] & pawn_attacks_bb[reverse_pawn][square]) return true;
    if (p->pieces[by_side][1] & knight_attacks_bb[square]) return true;
    if ((p->pieces[by_side][2] | p->pieces[by_side][4]) &
        bishop_attacks_ray(square, occupied)) return true;
    if ((p->pieces[by_side][3] | p->pieces[by_side][4]) &
        rook_attacks_ray(square, occupied)) return true;
    if (p->pieces[by_side][5] & king_attacks_bb[square]) return true;
    return false;
}

static bool bitboard_square_attacked(const Position *p, int square, Color by_side) {
    return bitboard_square_attacked_occ(p, square, by_side, p->occupied_all);
}

static bool bitboard_square_attacked_ep(const Position *p, int square,
                                        Color by_side, uint64_t occupied,
                                        uint64_t removed_pawn) {
    Color reverse_pawn = by_side == WHITE ? BLACK : WHITE;
    if ((p->pieces[by_side][0] & ~removed_pawn) &
        pawn_attacks_bb[reverse_pawn][square]) return true;
    if (p->pieces[by_side][1] & knight_attacks_bb[square]) return true;
    if ((p->pieces[by_side][2] | p->pieces[by_side][4]) &
        bishop_attacks_ray(square, occupied)) return true;
    if ((p->pieces[by_side][3] | p->pieces[by_side][4]) &
        rook_attacks_ray(square, occupied)) return true;
    if (p->pieces[by_side][5] & king_attacks_bb[square]) return true;
    return false;
}

typedef struct {
    int king_square;
    int check_count;
    uint64_t checkers;
    uint64_t pinned;
    uint64_t evasion_mask;
    uint64_t pin_ray[64];
} BitboardLegalInfo;

static uint64_t bitboard_between(int from, int to) {
    int df = file_of(to) - file_of(from), dr = rank_of(to) - rank_of(from);
    int step_file = sign_i(df), step_rank = sign_i(dr);
    if (!(df == 0 || dr == 0 || abs_i(df) == abs_i(dr))) return 0;
    uint64_t between = 0;
    int file = file_of(from) + step_file, rank = rank_of(from) + step_rank;
    while (file != file_of(to) || rank != rank_of(to)) {
        between |= square_bit(rank * 8 + file);
        file += step_file; rank += step_rank;
    }
    return between & ~square_bit(to);
}

static void compute_bitboard_legal_info(const Position *p,
                                        BitboardLegalInfo *info) {
    info->checkers = 0;
    info->pinned = 0;
    info->evasion_mask = 0;
    Color us = p->side_to_move, them = opposite(us);
    int king = p->king_sq[us];
    info->king_square = king;
    info->checkers |= p->pieces[them][0] & pawn_attacks_bb[us][king];
    info->checkers |= p->pieces[them][1] & knight_attacks_bb[king];
    info->checkers |= p->pieces[them][5] & king_attacks_bb[king];

    uint64_t enemy_bishop_sliders = p->pieces[them][2] | p->pieces[them][4];
    uint64_t enemy_rook_sliders = p->pieces[them][3] | p->pieces[them][4];
    info->checkers |= bishop_attacks_ray(king, p->occupied_all) &
                      enemy_bishop_sliders;
    info->checkers |= rook_attacks_ray(king, p->occupied_all) &
                      enemy_rook_sliders;

    /* Remove our pieces from occupancy to expose enemy sliders behind them.
     * A slider is a real pinner only when exactly one friendly piece lies
     * between it and the king. */
    uint64_t xray_occupancy = p->occupied_all & ~p->occupied[us];
    uint64_t pinners =
        (bishop_attacks_ray(king, xray_occupancy) & enemy_bishop_sliders) |
        (rook_attacks_ray(king, xray_occupancy) & enemy_rook_sliders);
    while (pinners) {
        int pinner = bitboard_pop_lsb(&pinners);
        uint64_t between = bitboard_between(king, pinner);
        uint64_t blockers = between & p->occupied[us];
        if (bitboard_popcount(blockers) == 1) {
            int pinned_square = bitboard_lsb(blockers);
            info->pinned |= blockers;
            info->pin_ray[pinned_square] = between | square_bit(pinner);
        }
    }

    info->check_count = bitboard_popcount(info->checkers);
    if (info->check_count == 1) {
        int checker = bitboard_lsb(info->checkers);
        info->evasion_mask = square_bit(checker) | bitboard_between(king, checker);
    } else if (info->check_count == 0) {
        info->evasion_mask = UINT64_MAX;
    }
}

static bool bitboard_move_legal_direct(const Position *p, Move move,
                                       const BitboardLegalInfo *info) {
    int from = MOVE_FROM(move), to = MOVE_TO(move);
    MoveFlag flag = MOVE_FLAG(move);
    Color us = p->side_to_move, them = opposite(us);
    Piece moving = p->board[from];

    if (flag == MOVE_EN_PASSANT) {
        int captured = to + (us == WHITE ? -8 : 8);
        uint64_t removed_pawn = square_bit(captured);
        uint64_t occupied = p->occupied_all & ~square_bit(from) & ~removed_pawn;
        occupied |= square_bit(to);
        return !bitboard_square_attacked_ep(p, p->king_sq[us], them,
                                            occupied, removed_pawn);
    }

    if (piece_type(moving) == 6) {
        uint64_t occupied = p->occupied_all & ~square_bit(from) & ~square_bit(to);
        occupied |= square_bit(to);
        if (flag == MOVE_KING_CASTLE || flag == MOVE_QUEEN_CASTLE) {
            int rook_from, rook_to, transit;
            if (flag == MOVE_KING_CASTLE) {
                rook_from = us == WHITE ? 7 : 63;
                rook_to = us == WHITE ? 5 : 61;
                transit = us == WHITE ? 5 : 61;
            } else {
                rook_from = us == WHITE ? 0 : 56;
                rook_to = us == WHITE ? 3 : 59;
                transit = us == WHITE ? 3 : 59;
            }
            uint64_t transit_occupied = (p->occupied_all & ~square_bit(from)) |
                                          square_bit(transit);
            if (bitboard_square_attacked_occ(p, from, them, p->occupied_all) ||
                bitboard_square_attacked_occ(p, transit, them, transit_occupied))
                return false;
            occupied &= ~square_bit(rook_from);
            occupied |= square_bit(rook_to);
        }
        return !bitboard_square_attacked_occ(p, to, them, occupied);
    }

    if (info->check_count >= 2) return false;
    uint64_t destination = square_bit(to);
    if ((info->pinned & square_bit(from)) && !(info->pin_ray[from] & destination))
        return false;
    if (info->check_count == 1 && !(info->evasion_mask & destination))
        return false;
    return true;
}

/* Stalemate detection still needs to know whether any quiet move exists when
 * qsearch has no legal tactical move. Walk candidates lazily and stop at the
 * first legal move instead of building and filtering a complete quiet list. */
static bool bitboard_has_any_legal_move(const Position *p,
                                        const BitboardLegalInfo *info) {
    Color us = p->side_to_move, them = opposite(us);
    uint64_t enemy = p->occupied[them] & ~p->pieces[them][5];
    uint64_t destinations_allowed = ~p->occupied[us] & ~p->pieces[them][5];
    int promotion_rank = us == WHITE ? 7 : 0;
    int start_rank = us == WHITE ? 1 : 6;

    uint64_t pawns = p->pieces[us][0];
    while (pawns) {
        int from = bitboard_pop_lsb(&pawns);
        int one = from + (us == WHITE ? 8 : -8);
        if (on_board(one) && !(p->occupied_all & square_bit(one))) {
            MoveFlag flag = rank_of(one) == promotion_rank ?
                            MOVE_PROMOTE_Q : MOVE_QUIET;
            if (bitboard_move_legal_direct(p, encode_move(from, one, flag), info))
                return true;
            int two = from + (us == WHITE ? 16 : -16);
            if (rank_of(from) == start_rank &&
                !(p->occupied_all & square_bit(two)) &&
                bitboard_move_legal_direct(
                    p, encode_move(from, two, MOVE_DOUBLE_PAWN_PUSH), info))
                return true;
        }
        uint64_t captures = pawn_attacks_bb[us][from] & enemy;
        while (captures) {
            int to = bitboard_pop_lsb(&captures);
            MoveFlag flag = rank_of(to) == promotion_rank ?
                            MOVE_PROMOTE_Q_CAPTURE : MOVE_CAPTURE;
            if (bitboard_move_legal_direct(p, encode_move(from, to, flag), info))
                return true;
        }
        if (p->ep_square >= 0 &&
            (pawn_attacks_bb[us][from] & square_bit(p->ep_square))) {
            int captured = p->ep_square + (us == WHITE ? -8 : 8);
            Piece expected = us == WHITE ? BP : WP;
            if (on_board(captured) && p->board[captured] == expected &&
                bitboard_move_legal_direct(
                    p, encode_move(from, p->ep_square, MOVE_EN_PASSANT), info))
                return true;
        }
    }

    for (int type = 1; type <= 4; ++type) {
        uint64_t pieces = p->pieces[us][type];
        while (pieces) {
            int from = bitboard_pop_lsb(&pieces);
            uint64_t destinations;
            if (type == 1) destinations = knight_attacks_bb[from];
            else if (type == 2) destinations = bishop_attacks_ray(from, p->occupied_all);
            else if (type == 3) destinations = rook_attacks_ray(from, p->occupied_all);
            else destinations = bishop_attacks_ray(from, p->occupied_all) |
                                rook_attacks_ray(from, p->occupied_all);
            destinations &= destinations_allowed;
            while (destinations) {
                int to = bitboard_pop_lsb(&destinations);
                MoveFlag flag = p->board[to] == EMPTY ? MOVE_QUIET : MOVE_CAPTURE;
                if (bitboard_move_legal_direct(
                        p, encode_move(from, to, flag), info))
                    return true;
            }
        }
    }

    uint64_t kings = p->pieces[us][5];
    if (kings) {
        int from = bitboard_lsb(kings);
        uint64_t destinations = king_attacks_bb[from] & destinations_allowed;
        while (destinations) {
            int to = bitboard_pop_lsb(&destinations);
            MoveFlag flag = p->board[to] == EMPTY ? MOVE_QUIET : MOVE_CAPTURE;
            if (bitboard_move_legal_direct(p, encode_move(from, to, flag), info))
                return true;
        }
    }
    return false;
}

/* Emit legal moves directly. Non-king destinations are intersected with the
 * check-evasion and pin masks before moves enter the list; only king moves and
 * en passant require an occupancy-specific attack test. */
typedef enum { GEN_ALL, GEN_TACTICAL, GEN_QUIET } GenerationMode;

static void generate_selected_moves(
        const Position *p, MoveList *legal, const BitboardLegalInfo *info,
        GenerationMode mode, uint64_t origins) {
    legal->count = 0;
    Color us = p->side_to_move, them = opposite(us);
    uint64_t own = p->occupied[us];
    uint64_t enemy = p->occupied[them] & ~p->pieces[them][5];
    uint64_t normal_targets = mode == GEN_TACTICAL ? enemy :
                              mode == GEN_QUIET ? ~p->occupied_all : (~own & ~p->pieces[them][5]);
    int promotion_rank = us == WHITE ? 7 : 0;
    int start_rank = us == WHITE ? 1 : 6;

    if (info->check_count < 2) {
        uint64_t pawns = p->pieces[us][0] & origins;
        while (pawns) {
            int from = bitboard_pop_lsb(&pawns);
            uint64_t allowed = info->evasion_mask;
            if (info->pinned & square_bit(from)) allowed &= info->pin_ray[from];

            int one = from + (us == WHITE ? 8 : -8);
            if (on_board(one) && !(p->occupied_all & square_bit(one))) {
                bool promotion = rank_of(one) == promotion_rank;
                if ((promotion ? mode != GEN_QUIET : mode != GEN_TACTICAL) && (allowed & square_bit(one))) {
                    if (promotion) add_promotions(legal, from, one, false);
                    else (void)add_move(legal, from, one, MOVE_QUIET);
                }
                if (mode != GEN_TACTICAL && !promotion && rank_of(from) == start_rank) {
                    int two = from + (us == WHITE ? 16 : -16);
                    if (!(p->occupied_all & square_bit(two)) &&
                        (allowed & square_bit(two)))
                        (void)add_move(legal, from, two, MOVE_DOUBLE_PAWN_PUSH);
                }
            }

            uint64_t captures = mode == GEN_QUIET ? 0 : pawn_attacks_bb[us][from] & enemy & allowed;
            while (captures) {
                int to = bitboard_pop_lsb(&captures);
                if (rank_of(to) == promotion_rank)
                    add_promotions(legal, from, to, true);
                else
                    (void)add_move(legal, from, to, MOVE_CAPTURE);
            }

            /* En passant can expose a rook/bishop line by removing a pawn from
             * a square other than the destination, so retain its exact test. */
            if (mode != GEN_QUIET && p->ep_square >= 0 &&
                (pawn_attacks_bb[us][from] & square_bit(p->ep_square))) {
                int captured = p->ep_square + (us == WHITE ? -8 : 8);
                Piece expected = us == WHITE ? BP : WP;
                Move move = encode_move(from, p->ep_square, MOVE_EN_PASSANT);
                if (on_board(captured) && p->board[captured] == expected &&
                    bitboard_move_legal_direct(p, move, info))
                    (void)add_move(legal, from, p->ep_square, MOVE_EN_PASSANT);
            }
        }

        for (int type = 1; type <= 4; ++type) {
            uint64_t pieces = p->pieces[us][type] & origins;
            while (pieces) {
                int from = bitboard_pop_lsb(&pieces);
                uint64_t destinations;
                if (type == 1) destinations = knight_attacks_bb[from];
                else if (type == 2)
                    destinations = bishop_attacks_ray(from, p->occupied_all);
                else if (type == 3)
                    destinations = rook_attacks_ray(from, p->occupied_all);
                else
                    destinations = bishop_attacks_ray(from, p->occupied_all) |
                                   rook_attacks_ray(from, p->occupied_all);
                destinations &= normal_targets & info->evasion_mask;
                if (info->pinned & square_bit(from))
                    destinations &= info->pin_ray[from];
                while (destinations) {
                    int to = bitboard_pop_lsb(&destinations);
                    MoveFlag flag = p->board[to] == EMPTY ?
                                    MOVE_QUIET : MOVE_CAPTURE;
                    (void)add_move(legal, from, to, flag);
                }
            }
        }
    }

    uint64_t kings = p->pieces[us][5] & origins;
    if (kings) {
        int from = bitboard_lsb(kings);
        uint64_t destinations = king_attacks_bb[from] & normal_targets;
        while (destinations) {
            int to = bitboard_pop_lsb(&destinations);
            MoveFlag flag = p->board[to] == EMPTY ? MOVE_QUIET : MOVE_CAPTURE;
            Move move = encode_move(from, to, flag);
            if (bitboard_move_legal_direct(p, move, info))
                (void)add_move(legal, from, to, flag);
        }

        if (mode != GEN_TACTICAL && info->check_count == 0) {
            Move castle[2];
            int castle_count = 0;
            if (us == WHITE && from == 4) {
                if ((p->castling_rights & CASTLE_WK) && p->board[7] == WR &&
                    !(p->occupied_all & (square_bit(5) | square_bit(6))))
                    castle[castle_count++] = encode_move(4, 6, MOVE_KING_CASTLE);
                if ((p->castling_rights & CASTLE_WQ) && p->board[0] == WR &&
                    !(p->occupied_all &
                      (square_bit(1) | square_bit(2) | square_bit(3))))
                    castle[castle_count++] = encode_move(4, 2, MOVE_QUEEN_CASTLE);
            } else if (us == BLACK && from == 60) {
                if ((p->castling_rights & CASTLE_BK) && p->board[63] == BR &&
                    !(p->occupied_all & (square_bit(61) | square_bit(62))))
                    castle[castle_count++] = encode_move(60, 62, MOVE_KING_CASTLE);
                if ((p->castling_rights & CASTLE_BQ) && p->board[56] == BR &&
                    !(p->occupied_all &
                      (square_bit(57) | square_bit(58) | square_bit(59))))
                    castle[castle_count++] = encode_move(60, 58, MOVE_QUEEN_CASTLE);
            }
            for (int i = 0; i < castle_count; ++i)
                if (bitboard_move_legal_direct(p, castle[i], info) &&
                    legal->count < MAX_MOVES)
                    legal->moves[legal->count++] = castle[i];
        }
    }
}

static void generate_bitboard_legal_moves_mode(const Position *p, MoveList *list,
        const BitboardLegalInfo *info, bool tactical_only) {
    generate_selected_moves(p, list, info, tactical_only ? GEN_TACTICAL : GEN_ALL, UINT64_MAX);
}

/* Validate both the destination and encoded flag using the production generator
 * for just this piece. This also rejects stale killers and conflicting flags. */
static bool single_move_is_legal(const Position *p, const BitboardLegalInfo *info, Move move) {
    if (!move || !(p->occupied[p->side_to_move] & square_bit(MOVE_FROM(move)))) return false;
    MoveList candidates;
    generate_selected_moves(p, &candidates, info, GEN_ALL, square_bit(MOVE_FROM(move)));
    return move_in_list(&candidates, move);
}

static void generate_legal_moves_bitboard_with_info(
        const Position *p, MoveList *legal, const BitboardLegalInfo *info) {
    generate_bitboard_legal_moves_mode(p, legal, info, false);
}

static void generate_legal_moves_bitboard(const Position *p, MoveList *legal) {
    BitboardLegalInfo info;
    compute_bitboard_legal_info(p, &info);
    generate_legal_moves_bitboard_with_info(p, legal, &info);
}

/* Qsearch uses every legal evasion in check, but otherwise returns only
 * captures, en passant, and promotions.  Quiet candidates are tested only
 * until one proves the position is not stalemate. */
/* Split qsearch preparation from tactical generation. This lets stand-pat
 * cutoffs avoid constructing and ordering a capture list while preserving
 * exact checkmate and stalemate detection. */
static bool prepare_qsearch_position(const Position *p, MoveList *legal,
                                     BitboardLegalInfo *bitboard_info,
                                     LegalInfo *info) {
    Color us = p->side_to_move;
    compute_bitboard_legal_info(p, bitboard_info);
    memset(info, 0, sizeof *info);
    info->king_sq = p->king_sq[us];
    info->check_count = bitboard_info->check_count;
    if (bitboard_info->check_count > 0) {
        generate_bitboard_legal_moves_mode(p, legal, bitboard_info, false);
        return legal->count > 0;
    }
    legal->count = 0;
    return bitboard_has_any_legal_move(p, bitboard_info);
}

static void generate_prepared_qsearch_moves(
        const Position *p, MoveList *legal,
        const BitboardLegalInfo *bitboard_info) {
    generate_bitboard_legal_moves_mode(p, legal, bitboard_info, true);
}

/* Production entry points shared by search and user interfaces. */
static void generate_legal_moves(const Position *p, MoveList *list) {
    generate_legal_moves_bitboard(p, list);
}


