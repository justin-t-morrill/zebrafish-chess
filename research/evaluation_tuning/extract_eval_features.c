/* Native sparse Texel feature extraction for the selected engine source.
 * Output: "TXFTR001", uint32 feature count, then packed (uint16,float)
 * records; index 65535 terminates each input row. */
#define main chess_engine_program_main
#ifndef TEXEL_ENGINE_SOURCE
#define TEXEL_ENGINE_SOURCE "../../history/engines/v5/source_5.0/chess.c"
#endif
#include TEXEL_ENGINE_SOURCE
#undef main

enum { PST_EG=192, MAT_MG=384, MAT_EG=388, MOB_MG=392, MOB_EG=396,
       BISHOP_PAIR_MG=400, BISHOP_PAIR_EG=401, PAWNS=402, KING=418,
       CASTLED=426, LOST_CASTLING=427, THREATS=467,
       PAWN_DETAILS=487, BISHOP_QUALITY=521, EXPORTED_FEATURES=533,
       ROW_END=65535 };

#pragma pack(push, 1)
typedef struct { uint16_t index; float value; } FeaturePair;
#pragma pack(pop)

static void add(double f[EXPORTED_FEATURES], int i, double v) { f[i] += v; }

static void pawn_features(const Position *p, double f[EXPORTED_FEATURES],
                          double mg, double eg) {
    int passed[2][8]={{0}}, doubled[2]={0}, backward[2]={0};
    for (int side=WHITE; side<=BLACK; ++side) {
        uint64_t pawns=p->pieces[side][0], remaining=pawns;
        while (remaining) {
            int sq=bitboard_pop_lsb(&remaining);
            int rank=side==WHITE ? rank_of(sq) : 7-rank_of(sq);
            if (pawn_is_passed_bitboard(p,(Color)side,sq)) ++passed[side][rank];
            else if (pawn_is_backward_candidate_bitboard(p,(Color)side,sq)) {
                int advance=sq+(side==WHITE?8:-8);
                if (!(p->occupied_all & square_bit(advance))) ++backward[side];
            }
        }
        for (int file=0; file<8; ++file) {
            int n=bitboard_popcount(pawns & bitboard_file_mask(file));
            if (n>1) doubled[side]+=n-1;
        }
    }
    for (int rank=2; rank<=6; ++rank) {
        int d=passed[WHITE][rank]-passed[BLACK][rank];
        add(f,PAWNS+rank-2,d*mg); add(f,PAWNS+5+rank-2,d*eg);
    }
    int d=doubled[WHITE]-doubled[BLACK];
    add(f,PAWNS+10,-d*mg); add(f,PAWNS+11,-d*eg);
    d=backward[WHITE]-backward[BLACK];
    add(f,PAWNS+12,-d*mg); add(f,PAWNS+13,-d*eg);
}

static void shelter_counts(const Position *p, Color side, int c[4]) {
    memset(c,0,4*sizeof c[0]);
    int kf=file_of(p->king_sq[side]), first;
    if (kf==6) first=5; else if (kf==2) first=0; else return;
    c[0]=1;
    int home=side==WHITE?1:6, advanced=side==WHITE?2:5;
    for (int file=first; file<first+3; ++file) {
        if (p->pieces[side][0]&square_bit(home*8+file)) ++c[1];
        else if (p->pieces[side][0]&square_bit(advanced*8+file)) ++c[2];
        else if (!side_has_pawn_on_file(p,side,file)) ++c[3];
    }
}

static uint64_t eval_attacks(const Position *p, Color side, int type, int from) {
    uint64_t a;
    if (type==2) a=knight_attacks_bb[from];
    else if (type==3) a=bishop_attacks_ray(from,p->occupied_all);
    else if (type==4) a=rook_attacks_ray(from,p->occupied_all);
    else a=bishop_attacks_ray(from,p->occupied_all)|rook_attacks_ray(from,p->occupied_all);
    return a & ~p->occupied[side];
}

static void attack_counts(const Position *p, Color side, int c[4], int *n) {
    memset(c,0,4*sizeof c[0]); *n=0;
    Color enemy=opposite(side);
    uint64_t zone=evaluation_king_zone(p->king_sq[enemy],enemy);
    for (int type=2; type<=5; ++type) {
        uint64_t pieces=p->pieces[side][type-1];
        while (pieces) {
            int from=bitboard_pop_lsb(&pieces);
            int hits=bitboard_popcount(eval_attacks(p,side,type,from)&zone);
            c[type-2]+=hits; if (hits) ++*n;
        }
    }
    if (*n>7) *n=7;
}

static void king_features(const Position *p, double f[EXPORTED_FEATURES],
                          double mg, double eg) {
    static const int weights[8]={0,0,50,75,88,94,97,99};
    int ws[4],bs[4]; shelter_counts(p,WHITE,ws); shelter_counts(p,BLACK,bs);
    for (int i=0;i<4;++i) add(f,KING+i,(ws[i]-bs[i])*mg);
    int wa[4],ba[4],wn,bn;
    attack_counts(p,WHITE,wa,&wn); attack_counts(p,BLACK,ba,&bn);
    double wf=mg*weights[wn]/400.0+eg*weights[wn]*3.0/4000.0;
    double bf=mg*weights[bn]/400.0+eg*weights[bn]*3.0/4000.0;
    for (int i=0;i<4;++i) add(f,KING+4+i,wa[i]*wf-ba[i]*bf);
    for (int side=WHITE;side<=BLACK;++side) {
        int sign=side==WHITE?1:-1, rank=side==WHITE?0:7, king=p->king_sq[side];
        bool castled=king==rank*8+6||king==rank*8+2;
        uint8_t rights=side==WHITE?(CASTLE_WK|CASTLE_WQ):(CASTLE_BK|CASTLE_BQ);
        if (castled) add(f,CASTLED,sign*mg);
        else if (!(p->castling_rights&rights)) add(f,LOST_CASTLING,sign*mg);
    }
}

static void position_features(const Position *p, double f[EXPORTED_FEATURES]) {
    memset(f,0,EXPORTED_FEATURES*sizeof f[0]);
    if (known_drawish_pawnless_endgame((const uint8_t (*)[7])p->piece_count)) return;
    int phase=p->pesto_phase>24?24:p->pesto_phase;
    double scale=rule50_scale_percent(p->halfmove_clock)/100.0;
    double mg=phase*scale/24.0, eg=(24-phase)*scale/24.0;
    for (int sq=0;sq<64;++sq) {
        Piece piece=p->board[sq]; if (piece==EMPTY) continue;
        Color side=piece_color(piece); int type=piece_type(piece)-1;
        int psq=side==WHITE?(sq^56):sq, file=file_of(psq);
        int group=type*32+rank_of(psq)*4+(file<4?file:7-file);
        int sign=side==WHITE?1:-1;
        add(f,group,sign*mg); add(f,PST_EG+group,sign*eg);
    }
    ActivityScore a[2]={evaluate_activity_for_side(p,WHITE),evaluate_activity_for_side(p,BLACK)};
    for (int type=2;type<=5;++type) {
        int i=type-2, material=p->piece_count[WHITE][type]-p->piece_count[BLACK][type];
        int mobility=a[WHITE].mobility_by_type[type]-a[BLACK].mobility_by_type[type];
        add(f,MAT_MG+i,material*mg); add(f,MAT_EG+i,material*eg);
        add(f,MOB_MG+i,mobility*mg); add(f,MOB_EG+i,mobility*eg);
    }
    int bishops=(p->piece_count[WHITE][3]>=2)-(p->piece_count[BLACK][3]>=2);
    add(f,BISHOP_PAIR_MG,bishops*mg); add(f,BISHOP_PAIR_EG,bishops*eg);
    pawn_features(p,f,mg,eg); king_features(p,f,mg,eg);
#ifdef HAS_THREAT_EVAL
    ThreatFeatureCounts threats=threat_feature_counts(p,a);
    for (int feature=0;feature<THREAT_FEATURE_COUNT;++feature) {
        int difference=threats.count[WHITE][feature]-threats.count[BLACK][feature];
        add(f,THREATS+2*feature,difference*mg);
        add(f,THREATS+2*feature+1,difference*eg);
    }
#endif
#ifdef HAS_PAWN_DETAIL_EVAL
    PawnDetailFeatures details=pawn_detail_feature_counts(p,a);
    for (int feature=0;feature<PAWN_DETAIL_FEATURE_COUNT;++feature) {
        int difference=details.count[WHITE][feature]-details.count[BLACK][feature];
        add(f,PAWN_DETAILS+2*feature,difference*mg);
        add(f,PAWN_DETAILS+2*feature+1,difference*eg);
    }
#endif
#ifdef HAS_BISHOP_QUALITY_EVAL
    BishopQualityFeatures bishop_quality=bishop_quality_feature_counts(a);
    for (int feature=0;feature<BISHOP_QUALITY_FEATURE_COUNT;++feature) {
        int difference=bishop_quality.count[WHITE][feature]-
                       bishop_quality.count[BLACK][feature];
        add(f,BISHOP_QUALITY+2*feature,difference*mg);
        add(f,BISHOP_QUALITY+2*feature+1,difference*eg);
    }
#endif
}

int main(int argc,char **argv) {
    if (argc<3||argc>5) { fprintf(stderr,"usage: extract_eval_features leaves.csv features.bin [eval.csv] [max_rows]\n"); return 2; }
    init_move_tables();
    FILE *in=fopen(argv[1],"rb"),*out=fopen(argv[2],"wb");
    if (!in||!out) return 3;
    FILE *eval_out=argc>=4?fopen(argv[3],"wb"):NULL;
    if (argc>=4&&!eval_out) return 3;
    int max_rows=argc>=5?atoi(argv[4]):0;
    if (eval_out) fprintf(eval_out,"row,eval_white,side,side_eval\n");
    fwrite("TXFTR001",1,8,out); uint32_t count=EXPORTED_FEATURES;
    fwrite(&count,sizeof count,1,out);
    char line[16384]; if (!fgets(line,sizeof line,in)) return 4;
    int row=0;
    while (fgets(line,sizeof line,in)) {
        char *comma=strchr(line,','); if (comma) *comma='\0';
        Position p; char error[256];
        if (!parse_fen(&p,line,error,sizeof error)) { fprintf(stderr,"bad FEN row %d: %s\n",row+1,error); return 5; }
        double dense[EXPORTED_FEATURES]; position_features(&p,dense);
        FeaturePair pairs[EXPORTED_FEATURES+1]; size_t used=0;
        for (int i=0;i<EXPORTED_FEATURES;++i) if (dense[i]!=0.0) {
            pairs[used].index=(uint16_t)i; pairs[used].value=(float)dense[i]; ++used;
        }
        pairs[used].index=ROW_END; pairs[used].value=0.0f; ++used;
        if (fwrite(pairs,sizeof pairs[0],used,out)!=used) return 6;
        if (eval_out) {
            int score=pesto_evaluate_uncached(&p);
            int white=p.side_to_move==WHITE?score:-score;
            fprintf(eval_out,"%d,%d,%d,%d\n",row,white,(int)p.side_to_move,score);
        }
        if (++row%100000==0) fprintf(stderr,"features %d\n",row);
        if (max_rows>0&&row>=max_rows) break;
    }
    fclose(in); fclose(out); if (eval_out) fclose(eval_out);
    fprintf(stderr,"feature rows %d\n",row); return 0;
}
