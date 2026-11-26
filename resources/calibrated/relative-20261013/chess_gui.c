/* Native Windows board interface. The GUI deliberately calls the same move
 * generator, game recorder, opening book, and engine as the text interface. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <process.h>
#include <uxtheme.h>
#include <math.h>

/* Minimal declarations for the flat GDI+ API keep this file valid C rather
 * than requiring the C++ GDI+ wrapper headers. */
typedef void GpImage;
typedef void GpGraphics;
typedef struct {
    UINT GdiplusVersion;
    void *DebugEventCallback;
    BOOL SuppressBackgroundThread;
    BOOL SuppressExternalCodecs;
} GuiGdiplusStartupInput;
__declspec(dllimport) int WINAPI GdiplusStartup(
    ULONG_PTR *, const GuiGdiplusStartupInput *, void *);
__declspec(dllimport) void WINAPI GdiplusShutdown(ULONG_PTR);
__declspec(dllimport) int WINAPI GdipLoadImageFromFile(const WCHAR *, GpImage **);
__declspec(dllimport) int WINAPI GdipDisposeImage(GpImage *);
__declspec(dllimport) int WINAPI GdipCreateFromHDC(HDC, GpGraphics **);
__declspec(dllimport) int WINAPI GdipDeleteGraphics(GpGraphics *);
__declspec(dllimport) int WINAPI GdipDrawImageRectI(
    GpGraphics *, GpImage *, INT, INT, INT, INT);
__declspec(dllimport) int WINAPI GdipSetInterpolationMode(GpGraphics *, int);

typedef enum {
    GUI_HUMAN_VS_HUMAN,
    GUI_HUMAN_VS_ENGINE,
    GUI_ENGINE_VS_ENGINE
} GuiPlayMode;

typedef struct {
    Position position;
    GameRecord game;
    GuiPlayMode mode;
    Color human_side;
    int selected_square;
    int last_from_square, last_to_square;
    int board_x, board_y, square_size;
    double base_seconds[2], increment_seconds[2];
    double lag_reserve_seconds;
    double remaining[2];
    double turn_started;
    bool clock_started;
    bool unlimited_clock[2];
    int max_depth;
    int threads;
    int strength_elo[2];
    int skill_elo[2][4];
    bool maximum_strength[2];
    char engine_version[TOURNAMENT_MAX_NAME];
    char opening[256];
    char status[256];
    bool game_over;
    bool final_pgn_printed;
    int strength_state[2];
    int strength_state_remaining[2];
} ChessGui;

enum { GUI_SKILL_TACTICS, GUI_SKILL_POSITIONAL, GUI_SKILL_DEFENSE,
       GUI_SKILL_ENDGAME, GUI_SKILL_COUNT };
/* Empirical response calibration from the 1,920-game 2+1 experiment.  The
 * first fit is deliberately shrunk toward 1.0 pending held-out validation. */
static const double gui_skill_response[GUI_SKILL_COUNT]={2.50,1.10,4.00,3.20};
typedef struct {
    double weight[GUI_SKILL_COUNT];
    int captures, promotions, checking_moves, king_zone_pressure, piece_count;
    bool in_check;
} GuiMoveClassification;

static ChessGui gui;
static const wchar_t *GUI_CLASS_NAME = L"MinimalCChessWindow";
#define GUI_ENGINE_MOVE_MESSAGE (WM_APP + 1)
#define GUI_ENGINE_RESULT_MESSAGE (WM_APP + 2)
static HWND gui_base_edit[2], gui_increment_edit[2], gui_depth_edit;
static HWND gui_threads_edit;
static HWND gui_match_a_edit, gui_match_b_edit, gui_match_games_edit;
static HWND gui_lag_edit, gui_unlimited_check[2], gui_engine_combo;
static HWND gui_strength_slider[2], gui_strength_max_check[2], gui_nnue_check;
static HWND gui_strength_edit[2];
enum { GUI_PANEL_PLAY, GUI_PANEL_SETTINGS, GUI_PANEL_STRENGTH, GUI_PANEL_MATCH };
static int gui_active_panel=GUI_PANEL_PLAY;
/* Orientation is display state only; square indices remain a1=0. */
static bool gui_board_flipped;
static int gui_display_square(int display_file, int display_rank) {
    int file = gui_board_flipped ? 7 - display_file : display_file;
    int rank = gui_board_flipped ? display_rank : 7 - display_rank;
    return rank * 8 + file;
}
static atomic_bool gui_search_running=ATOMIC_VAR_INIT(false);
static atomic_bool gui_window_closing=ATOMIC_VAR_INIT(false);
static HANDLE gui_search_thread;
static unsigned gui_startup_seed;
static unsigned gui_decision_index;
static unsigned gui_game_first_decision_index = 1;
#define GUI_CANDIDATE_REVISION "relative-20261013-gui-worker-seed-v1"
/* Called only on the seeded window thread. Seed each new search worker,
 * because the Windows CRT rand state belongs to the calling thread. */
static unsigned gui_next_search_seed(void) {
    unsigned high = (unsigned)rand();
    unsigned low = (unsigned)rand();
    return (high << 16) ^ low;
}
static HBRUSH gui_control_brush;
static HFONT gui_ui_font;

typedef struct {
    HWND window;
    Position position;
    MoveList legal;
    Color mover;
    Move move;
    bool found;
    bool selected_current;
    bool maximum_strength;
    bool unlimited;
    int max_depth;
    int requested_elo;
    unsigned random_seed;
    unsigned decision_index;
    double budget;
    double base;
    double increment;
    char engine_version[TOURNAMENT_MAX_NAME];
} GuiSearchJob;
static ULONG_PTR gui_gdiplus_token;
static GpImage *gui_piece_images[13];
static void gui_schedule_engine_if_needed(HWND window);
static double gui_clock_value(Color side);

static void gui_show_control(HWND control,bool show) {
    if(control)ShowWindow(control,show?SW_SHOW:SW_HIDE);
}

static void gui_update_panel_visibility(void) {
    bool settings=gui_active_panel==GUI_PANEL_SETTINGS;
    bool strength=gui_active_panel==GUI_PANEL_STRENGTH;
    bool match=gui_active_panel==GUI_PANEL_MATCH;
    for(int side=WHITE;side<=BLACK;++side) {
        gui_show_control(gui_base_edit[side],settings);
        gui_show_control(gui_increment_edit[side],settings);
        gui_show_control(gui_unlimited_check[side],settings);
        gui_show_control(gui_strength_slider[side],strength);
        gui_show_control(gui_strength_edit[side],strength);
        gui_show_control(gui_strength_max_check[side],strength);
    }
    gui_show_control(gui_depth_edit,settings);
    gui_show_control(gui_threads_edit,settings);
    gui_show_control(gui_lag_edit,settings);
    gui_show_control(gui_engine_combo,settings);
    gui_show_control(gui_nnue_check,settings);
    gui_show_control(gui_match_a_edit,match);
    gui_show_control(gui_match_b_edit,match);
    gui_show_control(gui_match_games_edit,match);
}

static void gui_theme_control(HWND control) {
    if(!control)return;
    SetWindowTheme(control,L"DarkMode_Explorer",NULL);
    if(gui_ui_font)SendMessageW(control,WM_SETFONT,(WPARAM)gui_ui_font,TRUE);
}

typedef struct {
    const char *version;
    const wchar_t *label;
} GuiEngineOption;

typedef struct {
    int elo;
    int multipv;
    double temperature_cp;
    double normal_fraction;
    double rushed_probability;
    double oversight_probability;
    double take_mate_probability;
    double avoid_mate_probability;
    double focused_probability;
} GuiStrengthAnchor;

/* These anchors define a human-perception model, not just score noise. Lower
 * levels search less deeply, enter rushed/oversight states more often, and
 * recognize immediate mates less consistently. */
static const GuiStrengthAnchor gui_strength_anchors[] = {
    {-100,16,456.3,1.0,.6300,.3510,.0840,.0000,.0000},
    { 400,16,274.3,1.0,.4120,.1920,.4430,.3430,.0208},
    { 600,16,201.5,1.0,.3250,.1285,.5865,.4874,.0296},
    { 800,15,148.2,1.0,.2420,.0810,.7595,.6695,.0483},
    {1000,13,117.4,1.0,.1800,.0520,.8590,.7870,.0680},
    {1200,12, 93.3,1.0,.1266,.0322,.9212,.8689,.0867},
    {1500,10, 61.0,1.0,.0869,.0176,.9714,.9463,.1314},
    {1800, 9, 47.7,1.0,.0602,.0104,.9899,.9765,.1796},
    {2100, 7, 49.2,1.0,.0371,.0054,.9982,.9915,.2387},
    {2400, 5, 36.7,1.0,.0230,.0026,1.0, .9985,.3018},
    {2600, 4, 28.5,1.0,.0151,.0015,1.0,1.0,.3496},
    {2800, 1,  0.0,1.0,0.0,0.0,1.0,1.0,.45}
};

static GuiStrengthAnchor gui_strength_profile(double elo) {
    const size_t count = sizeof(gui_strength_anchors) /
                         sizeof(gui_strength_anchors[0]);
    if (elo <= gui_strength_anchors[0].elo) return gui_strength_anchors[0];
    if (elo >= gui_strength_anchors[count - 1].elo)
        return gui_strength_anchors[count - 1];
    for (size_t i = 1; i < count; ++i) {
        if (elo > gui_strength_anchors[i].elo) continue;
        const GuiStrengthAnchor *a = &gui_strength_anchors[i - 1];
        const GuiStrengthAnchor *b = &gui_strength_anchors[i];
        double f = (double)(elo - a->elo) / (double)(b->elo - a->elo);
        GuiStrengthAnchor r;
        r.elo = (int)(elo+.5);
        r.multipv = (int)(a->multipv + f * (b->multipv-a->multipv)+.5);
#define GUI_INTERPOLATE(field) r.field = a->field + f * (b->field-a->field)
        GUI_INTERPOLATE(temperature_cp);
        GUI_INTERPOLATE(normal_fraction);
        GUI_INTERPOLATE(rushed_probability);
        GUI_INTERPOLATE(oversight_probability);
        GUI_INTERPOLATE(take_mate_probability);
        GUI_INTERPOLATE(avoid_mate_probability);
        GUI_INTERPOLATE(focused_probability);
#undef GUI_INTERPOLATE
        return r;
    }
    return gui_strength_anchors[count - 1];
}

#include "relative_fit_uncertainty.h"

static bool gui_move_is_mate_in_one(const Position *position, Move move) {
    Position child=*position; make_move(&child,move);
    MoveList replies; generate_legal_moves(&child,&replies);
    return replies.count==0 && side_in_check(&child,child.side_to_move);
}

static bool gui_move_allows_mate_in_one(const Position *position, Move move) {
    Position child=*position; make_move(&child,move);
    MoveList replies; generate_legal_moves(&child,&replies);
    for(int i=0;i<replies.count;++i)
        if(gui_move_is_mate_in_one(&child,replies.moves[i])) return true;
    return false;
}

static double gui_random_unit(void) {
    return (double)rand()/((double)RAND_MAX+1.0);
}

/* Inverse of the combined 2+1 CCRL-Blitz calibration.  requested_elo is the
 * user-facing target; the returned value selects the previously tested
 * weakening behavior.  The 400 experiment bottomed out near 516, so the GUI
 * deliberately starts at the validated 500 target rather than mislabel it. */
#include "relative_mapping.h"
static double gui_legacy_strength_control_elo(double requested_elo) {
    static const int rating[] =
        {500,600,700,834,1149,1335,1476,1626,1724,1930,2425,2592,2954};
    static const int control[] =
        {120,263,407,600,800,1000,1200,1500,1800,2100,2400,2600,2800};
    const int count=(int)(sizeof(rating)/sizeof(rating[0]));
    if(requested_elo<=rating[0])return control[0];
    if(requested_elo>=rating[count-1])return control[count-1];
    int i=1;while(i<count&&requested_elo>rating[i])++i;
    double f=(double)(requested_elo-rating[i-1])/(rating[i]-rating[i-1]);
    return control[i-1]+f*(control[i]-control[i-1]);
}

static double gui_strength_control_elo(int requested_elo) {
    return gui_legacy_strength_control_elo(gui_relative_internal_setting(requested_elo));
}

enum { GUI_STATE_NORMAL, GUI_STATE_RUSHED, GUI_STATE_OVERSIGHT, GUI_STATE_FOCUSED };

static bool gui_flag_is_capture(MoveFlag flag) {
    return flag == MOVE_CAPTURE || flag == MOVE_EN_PASSANT ||
           flag == MOVE_PROMOTE_N_CAPTURE || flag == MOVE_PROMOTE_B_CAPTURE ||
           flag == MOVE_PROMOTE_R_CAPTURE || flag == MOVE_PROMOTE_Q_CAPTURE;
}

static int gui_position_piece_count(const Position *p) {
    int count=0;
    for(int sq=0;sq<64;++sq) if(p->board[sq]!=EMPTY) ++count;
    return count;
}

static uint64_t gui_attacks_by_side(const Position *p, Color side) {
    uint64_t attacks=0, scan=p->pieces[side][0];
    while(scan){int sq=bitboard_pop_lsb(&scan);attacks|=pawn_attacks_bb[side][sq];}
    scan=p->pieces[side][1];
    while(scan){int sq=bitboard_pop_lsb(&scan);attacks|=knight_attacks_bb[sq];}
    scan=p->pieces[side][2]|p->pieces[side][4];
    while(scan){int sq=bitboard_pop_lsb(&scan);attacks|=bishop_attacks_ray(sq,p->occupied_all);}
    scan=p->pieces[side][3]|p->pieces[side][4];
    while(scan){int sq=bitboard_pop_lsb(&scan);attacks|=rook_attacks_ray(sq,p->occupied_all);}
    return attacks|king_attacks_bb[p->king_sq[side]];
}

/* This is deliberately a cheap, overlapping position classifier rather than
 * a second search. A position may test several skills at once. */
static GuiMoveClassification gui_classify_move_decision(
        const Position *p,const MoveList *legal) {
    GuiMoveClassification c; memset(&c,0,sizeof c);
    Color us=p->side_to_move,them=(Color)(us^1);
    c.piece_count=gui_position_piece_count(p); c.in_check=side_in_check(p,us);
    for(int i=0;i<legal->count;++i) {
        Move m=legal->moves[i]; MoveFlag f=MOVE_FLAG(m);
        if(gui_flag_is_capture(f))++c.captures;
        if(flag_is_promotion(f))++c.promotions;
        Position child=*p; make_move(&child,m);
        if(side_in_check(&child,child.side_to_move))++c.checking_moves;
    }
    uint64_t zone=king_attacks_bb[p->king_sq[us]]|square_bit(p->king_sq[us]);
    c.king_zone_pressure=bitboard_popcount(gui_attacks_by_side(p,them)&zone);
    double forcing=(double)(c.captures+2*c.checking_moves+2*c.promotions)/
                   (double)(legal->count?legal->count:1);
    if(forcing>1.0)forcing=1.0;
    double phase=(double)p->pesto_phase/24.0;
    if(phase<0.0)phase=0.0;
    if(phase>1.0)phase=1.0;
    c.weight[GUI_SKILL_TACTICS]=.12+.58*forcing+.18*(c.in_check?1.0:0.0);
    c.weight[GUI_SKILL_DEFENSE]=.08+.72*(c.in_check?1.0:0.0)+
        .055*(c.king_zone_pressure>6?6:c.king_zone_pressure);
    c.weight[GUI_SKILL_ENDGAME]=(.06+.70*(1.0-phase)+
        (c.piece_count<=10?.18:0.0))*(1.0-.78*forcing)*
        (c.in_check?.45:1.0);
    c.weight[GUI_SKILL_POSITIONAL]=.18+.48*(1.0-forcing)*phase;
    double total=0.0;for(int i=0;i<GUI_SKILL_COUNT;++i)total+=c.weight[i];
    for(int i=0;i<GUI_SKILL_COUNT;++i)c.weight[i]/=total;
    return c;
}

static double gui_blended_skill_elo(const ChessGui *g,Color side,int overall,
                                    const GuiMoveClassification *c) {
    double mean=0.0,variance=0.0; bool customized=false;
    for(int i=0;i<GUI_SKILL_COUNT;++i) {
        int raw=g->skill_elo[side][i]>0?g->skill_elo[side][i]:overall;
        double delta=raw-overall;
        double response=1.0+(gui_skill_response[i]-1.0)/(1.0+fabs(delta)/200.0);
        double v=overall+response*delta;
        if(v!=overall)customized=true;
        mean+=c->weight[i]*v;
    }
    if(!customized)return overall; /* exact legacy-behavior invariant */
    for(int i=0;i<GUI_SKILL_COUNT;++i) {
        int raw=g->skill_elo[side][i]>0?g->skill_elo[side][i]:overall;
        double delta=raw-overall;
        double response=1.0+(gui_skill_response[i]-1.0)/(1.0+fabs(delta)/200.0);
        double v=overall+response*delta;
        double d=v-mean;variance+=c->weight[i]*d*d;
    }
    double blended=mean-.10*sqrt(variance);
    if(blended<500.0)blended=500.0;
    if(blended>2800.0)blended=2800.0;
    return blended;
}

static void gui_print_move_classification(const GuiMoveClassification *c,
                                          int overall,double blended) {
    printf("Decision classification: tactics %.1f%%, positional %.1f%%, defense %.1f%%, endgame %.1f%% | captures %d, checks %d, promotions %d, king pressure %d, pieces %d%s | strength %.0f -> %.0f\n",
        100*c->weight[0],100*c->weight[1],100*c->weight[2],100*c->weight[3],
        c->captures,c->checking_moves,c->promotions,c->king_zone_pressure,
        c->piece_count,c->in_check?", in check":"",(double)overall,blended);
}

/* Optional overall-rating overrides remain useful for automated GUI tests.
 * Hidden categories always follow Overall until calibration is validated. */
static void gui_load_skill_overrides(void) {
    static const char *side_name[2]={"WHITE","BLACK"};
    for(int side=WHITE;side<=BLACK;++side) {
        char overall_name[64],overall_value[32];
        snprintf(overall_name,sizeof overall_name,"CHESS_%s_OVERALL_ELO",side_name[side]);
        DWORD overall_n=GetEnvironmentVariableA(overall_name,overall_value,sizeof overall_value);
        if(overall_n>0&&overall_n<sizeof overall_value) {
            char *end=NULL;long rating=strtol(overall_value,&end,10);
            if(end!=overall_value&&*end=='\0'&&rating>=600&&rating<=2600) {
                gui.strength_elo[side]=(int)rating;gui.maximum_strength[side]=false;
            }
        }
        for(int skill=0;skill<GUI_SKILL_COUNT;++skill)
            gui.skill_elo[side][skill]=0;
    }
}

static int run_strength_classifier_diagnostics(void) {
    static const struct { const char *name,*fen; int expected; } cases[]={
        {"quiet opening","rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",GUI_SKILL_POSITIONAL},
        {"king under attack","4k3/8/8/8/8/8/3q4/3RK3 w - - 0 1",GUI_SKILL_DEFENSE},
        {"forcing tactics","4k3/8/8/3q4/4R3/8/8/4K3 w - - 0 1",GUI_SKILL_TACTICS},
        {"pawn ending","8/5pk1/6p1/8/4P3/5K2/8/8 w - - 0 1",GUI_SKILL_ENDGAME}
    };
    const char *names[]={"tactics","positional","defense","endgame"};
    int failures=0; double start=timer_seconds();
    for(size_t n=0;n<sizeof cases/sizeof cases[0];++n) {
        Position p;char error[128];MoveList legal;
        if(!parse_fen(&p,cases[n].fen,error,sizeof error)){printf("FAIL %s: %s\n",cases[n].name,error);++failures;continue;}
        generate_legal_moves(&p,&legal);
        GuiMoveClassification c=gui_classify_move_decision(&p,&legal);
        double sum=0.0;int largest=0;
        for(int i=0;i<GUI_SKILL_COUNT;++i){sum+=c.weight[i];if(c.weight[i]>c.weight[largest])largest=i;}
        bool normalized=fabs(sum-1.0)<1e-9;
        /* Quiet openings overlap enough that positional need only exceed
         * tactics; the other diagnostic positions should have the named
         * category as their largest demand. */
        bool expected=n==0?c.weight[GUI_SKILL_POSITIONAL]>c.weight[GUI_SKILL_TACTICS]:largest==cases[n].expected;
        printf("%s: T %.3f P %.3f D %.3f E %.3f; dominant %s; %s\n",cases[n].name,
            c.weight[0],c.weight[1],c.weight[2],c.weight[3],names[largest],
            normalized&&expected?"PASS":"FAIL");
        if(!normalized||!expected)++failures;
        ChessGui test;memset(&test,0,sizeof test);
        if(gui_blended_skill_elo(&test,p.side_to_move,1500,&c)!=1500.0){printf("FAIL balanced-profile invariant\n");++failures;}
        for(int i=0;i<GUI_SKILL_COUNT;++i)test.skill_elo[p.side_to_move][i]=1500;
        test.skill_elo[p.side_to_move][cases[n].expected]=900;
        double weak=gui_blended_skill_elo(&test,p.side_to_move,1500,&c);
        if(weak>=1500.0){printf("FAIL weak relevant skill did not lower blend\n");++failures;}
        else printf("  weak-%s profile blends to %.0f\n",names[cases[n].expected],weak);
    }
    Position p;init_position(&p);MoveList legal;generate_legal_moves(&p,&legal);
    for(int i=0;i<20000;++i)(void)gui_classify_move_decision(&p,&legal);
    double micros=(timer_seconds()-start)*1000000.0/20000.0;
    printf("Classifier diagnostic: %s; representative cost %.2f us/call\n",failures?"FAILED":"PASSED",micros);
    return failures?1:0;
}

/* Human candidate salience: forcing moves, recaptures, development, castling,
 * and promotions are more likely to be considered than arbitrary legal moves.
 * This changes candidate selection, rather than merely adding evaluation noise. */
static double gui_human_move_weight(const Position *p, Move move, double elo) {
    int from=MOVE_FROM(move), to=MOVE_TO(move);
    MoveFlag flag=MOVE_FLAG(move);
    int type=piece_type(p->board[from]);
    double weight=1.0;
    if(gui_flag_is_capture(flag)) weight*=2.2;
    if(gui.last_to_square==to && gui_flag_is_capture(flag)) weight*=1.7;
    if(flag_is_promotion(flag)) weight*=3.0;
    if(flag==MOVE_KING_CASTLE || flag==MOVE_QUEEN_CASTLE) weight*=2.4;
    if((type==2 || type==4) && ((p->side_to_move==WHITE && from/8==0) ||
       (p->side_to_move==BLACK && from/8==7))) weight*=1.45;
    if(type==1) weight*=1.12;
    if(type==5 && p->history_count<13) weight*=.68;
    if(type==6 && flag!=MOVE_KING_CASTLE && flag!=MOVE_QUEEN_CASTLE &&
       p->history_count<21) weight*=.72;
    Position child=*p; make_move(&child,move);
    if(side_in_check(&child,child.side_to_move)) weight*=2.0;
    /* Candidate preferences matter most for novices and fade toward maximum
     * strength, where the searched score should dominate. */
    double influence=(2800-elo)/1800.0;
    if(influence<0.0) influence=0.0;
    if(influence>1.0) influence=1.0;
    return pow(weight,.35+.65*influence);
}

static Move gui_weighted_legal_move(const Position *p,const MoveList *legal,
                                    const int *indices,int count,double elo) {
    double total=0.0,weights[MAX_MOVES];
    for(int i=0;i<count;++i) {
        weights[i]=gui_human_move_weight(p,legal->moves[indices[i]],elo);
        total+=weights[i];
    }
    double draw=gui_random_unit()*total;
    for(int i=0;i<count;++i) {
        draw-=weights[i];
        if(draw<=0.0) return legal->moves[indices[i]];
    }
    return legal->moves[indices[count-1]];
}

static bool gui_choose_reduced_strength_move(const Position *position,
                                             const MoveList *legal,
                                             int max_depth,double budget,
                                             int requested_elo,Move *out) {
    if(legal->count<=0) return false;
    double started=timer_seconds();
    GuiMoveClassification classification=gui_classify_move_decision(position,legal);
    double blended_elo=gui_blended_skill_elo(&gui,position->side_to_move,
                                              requested_elo,&classification);
    gui_print_move_classification(&classification,requested_elo,blended_elo);
    double strength_control=gui_strength_control_elo((int)(blended_elo+.5));
    GuiStrengthAnchor p=gui_strength_profile(strength_control);
    Color mover=position->side_to_move;
    int pieces=gui_position_piece_count(position);
    bool in_check=side_in_check(position,mover);
    bool unlimited=gui.unlimited_clock[mover];
    double reaction_floor=.18+(2800-strength_control)/2400.0*.22;
    if(reaction_floor<.18)reaction_floor=.18;
    if(reaction_floor>.45)reaction_floor=.45;
    double move_time=budget;
    int recaptures=0;
    for(int i=0;i<legal->count;++i)
        if(gui.last_to_square>=0 && MOVE_TO(legal->moves[i])==gui.last_to_square &&
           gui_flag_is_capture(MOVE_FLAG(legal->moves[i]))) ++recaptures;
    bool obvious_recapture=recaptures==1;
    if(legal->count==1) {
        *out=legal->moves[0];
        move_time=reaction_floor;
        printf("Reduced strength %d: forced move (%.2f s reaction)\n",requested_elo,move_time);
        goto wait_and_return;
    }
    if(!unlimited) {
        /* The normal engine allocation is a ceiling. Humans commonly spend
         * only part of it, saving the rest for genuinely difficult positions. */
        double use=.68;
        if(legal->count<=1)use=.18;
        else if(obvious_recapture)use=.32;
        else if(in_check && legal->count<=6)use=.42;
        else if(legal->count>=30)use=.95;
        else if(legal->count>=22)use=.82;
        if(pieces<=10 && legal->count<20)use*=.82;
        /* Small non-determinism avoids metronomic clock use. Lower-rated play
         * varies more, but the factor never gives extra search beyond budget. */
        double jitter_span=.05+(2800-strength_control)/2400.0*.16;
        use*=1.0+jitter_span*(2.0*gui_random_unit()-1.0);
        double ratio=gui.base_seconds[mover]>0.0 ?
                     gui_clock_value(mover)/gui.base_seconds[mover] : 1.0;
        if(ratio<.05)use*=.30;
        else if(ratio<.15)use*=.50;
        else if(ratio<.30)use*=.72;
        if(use>.98)use=.98;
        if(use<.05)use=.05;
        move_time=budget*use;
        if(move_time<reaction_floor)move_time=reaction_floor;
        double clock_left=gui_clock_value(mover);
        if(clock_left>0.0 && move_time>clock_left*.80)move_time=clock_left*.80;
        if(move_time<.01)move_time=.01;
    }

    /* Rating-dependent opening knowledge uses the real weighted book. Weak
     * levels know fewer plies and sometimes leave preparation; strong levels
     * retain substantially more of the repertoire. */
    int known_plies=(int)(4+(strength_control-400)*18/2400);
    if(known_plies<0)known_plies=0;
    double opening_familiarity=.18+(strength_control-400)/2400.0*.80;
    if(opening_familiarity<0.0)opening_familiarity=0.0;
    if(opening_familiarity>1.0)opening_familiarity=1.0;
    if(position->history_count-1<known_plies &&
       gui_random_unit()<opening_familiarity &&
       choose_opening_book_move(position,legal,out)) {
        move_time=reaction_floor;
        printf("Reduced strength %d: familiar opening move (%.2f s reaction)\n",requested_elo,move_time);
        goto wait_and_return;
    }

    double rushed=p.rushed_probability, oversight_p=p.oversight_probability;
    double focused=p.focused_probability;
    double tactics_delta=(gui.skill_elo[mover][GUI_SKILL_TACTICS]-requested_elo)/1000.0;
    double defense_delta=(gui.skill_elo[mover][GUI_SKILL_DEFENSE]-requested_elo)/1000.0;
    double endgame_delta=(gui.skill_elo[mover][GUI_SKILL_ENDGAME]-requested_elo)/1000.0;
    if(gui.skill_elo[mover][GUI_SKILL_TACTICS]>0)
        oversight_p*=exp(-tactics_delta*classification.weight[GUI_SKILL_TACTICS]);
    if(gui.skill_elo[mover][GUI_SKILL_DEFENSE]>0)
        oversight_p*=exp(-defense_delta*classification.weight[GUI_SKILL_DEFENSE]);
    if(gui.skill_elo[mover][GUI_SKILL_ENDGAME]>0&&pieces<=14)
        focused+=.10*endgame_delta*classification.weight[GUI_SKILL_ENDGAME];
    /* Position difficulty and clock pressure alter the chance of a shallow or
     * missed calculation. Forced/check positions are easier; crowded, highly
     * branching positions are harder. */
    if(legal->count<=2 || in_check) { rushed*=.55; oversight_p*=.35; }
    else if(legal->count>=30) { rushed*=1.18; oversight_p*=1.28; }
    if(!gui.unlimited_clock[mover] && gui.base_seconds[mover]>0.0) {
        double ratio=gui_clock_value(mover)/gui.base_seconds[mover];
        if(ratio<.05){rushed*=2.0;oversight_p*=3.0;}
        else if(ratio<.15){rushed*=1.55;oversight_p*=2.0;}
        else if(ratio<.30){rushed*=1.22;oversight_p*=1.40;}
    }
    /* Sparse endings reward learned technique. This is deliberately
     * probabilistic at low ratings and nearly automatic at high ratings. */
    if(pieces<=10) {
        double endgame_knowledge=.20+(strength_control-400)/2400.0*.78;
        if(endgame_knowledge<0.0)endgame_knowledge=0.0;
        if(endgame_knowledge>1.0)endgame_knowledge=1.0;
        if(gui_random_unit()<endgame_knowledge) focused+=.16;
        else { rushed*=1.18; oversight_p*=1.15; }
    }
    if(rushed+oversight_p+focused>.95) {
        double scale=.95/(rushed+oversight_p+focused);
        rushed*=scale; oversight_p*=scale; focused*=scale;
    }

    int state;
    if(gui.strength_state_remaining[mover]>0) {
        state=gui.strength_state[mover];
        --gui.strength_state_remaining[mover];
    } else {
        double draw=gui_random_unit();
        if(draw<oversight_p) state=GUI_STATE_OVERSIGHT;
        else if(draw<oversight_p+rushed) state=GUI_STATE_RUSHED;
        else if(draw<oversight_p+rushed+focused) state=GUI_STATE_FOCUSED;
        else state=GUI_STATE_NORMAL;
        gui.strength_state[mover]=state;
        /* Oversights and time trouble can affect the following decision too;
         * persistence decreases smoothly with rating. */
        double persistence=(2800-strength_control)/2400.0;
        if(persistence<0.0)persistence=0.0;
        if(persistence>1.0)persistence=1.0;
        if((state==GUI_STATE_OVERSIGHT || state==GUI_STATE_RUSHED) &&
           gui_random_unit()<.10+.38*persistence)
            gui.strength_state_remaining[mover]=1+(gui_random_unit()<.22*persistence);
    }
    const char *state_name="normal";
    double fraction=p.normal_fraction,temperature=p.temperature_cp;
    bool oversight=false;
    if(state==GUI_STATE_OVERSIGHT){state_name="oversight";oversight=true;fraction=.01;temperature=1000.0;}
    else if(state==GUI_STATE_RUSHED){state_name="rushed";fraction=fmax(.02,p.normal_fraction*.35);temperature=p.temperature_cp*1.45;}
    else if(state==GUI_STATE_FOCUSED){state_name="focused";fraction=1.0;temperature=p.temperature_cp*.55;}
    if(!unlimited) {
        if(state==GUI_STATE_RUSHED)move_time=fmax(reaction_floor,move_time*.58);
        else if(state==GUI_STATE_OVERSIGHT)move_time=fmax(reaction_floor,move_time*.42);
        else if(state==GUI_STATE_FOCUSED)move_time=fmin(budget,move_time*1.22);
    }

    Move mate_moves[MAX_MOVES]; int mate_count=0;
    for(int i=0;i<legal->count;++i)
        if(gui_move_is_mate_in_one(position,legal->moves[i]))
            mate_moves[mate_count++]=legal->moves[i];
    if(mate_count>0 && gui_random_unit()<p.take_mate_probability) {
        *out=mate_moves[rand()%mate_count];
        move_time=reaction_floor;
        printf("Reduced strength %d: %s, recognized mate in one (%.2f s reaction)\n",requested_elo,state_name,move_time);
        goto wait_and_return;
    }

    bool use_avoid_guard=gui_random_unit()<p.avoid_mate_probability;
    if(oversight) {
        int choices[MAX_MOVES],count=0;
        for(int i=0;i<legal->count;++i)
            if(!use_avoid_guard || !gui_move_allows_mate_in_one(position,legal->moves[i])) choices[count++]=i;
        if(count==0) for(int i=0;i<legal->count;++i) choices[count++]=i;
        *out=gui_weighted_legal_move(position,legal,choices,count,strength_control);
        if(!unlimited)move_time=fmax(reaction_floor,move_time*.55);
        printf("Reduced strength %d: persistent %s, weighted human candidate%s\n",
               requested_elo,state_name,use_avoid_guard?", mate awareness active":"");
        goto wait_and_return;
    }

    int width=p.multipv; if(width>legal->count)width=legal->count;
    if(width<1)width=1;
    if(budget<.001)budget=.001;
    double search_budget=fmax(.001,move_time*fraction);
    SearchResult lines[16]; Move excluded[16]; bool unsafe[16]; int found=0;
    int prior_threads=search_thread_count; search_thread_count=1;
    atomic_bool stop=ATOMIC_VAR_INIT(false);
    for(int rank=0;rank<width;++rank) {
        lines[rank]=search_best_move_controlled(position,search_budget/width,max_depth,&stop,0,NULL,NULL,false,
            encode_move(0,0,MOVE_QUIET),excluded,found);
        if(!lines[rank].found)break;
        excluded[found]=lines[rank].move;
        unsafe[found]=gui_move_allows_mate_in_one(position,lines[rank].move);
        ++found;
    }
    search_thread_count=prior_threads;
    if(found==0)return false;
    bool has_safe=false; for(int i=0;i<found;++i)has_safe=has_safe||!unsafe[i];
    bool filter_unsafe=has_safe&&use_avoid_guard;
    /* A position with one clearly superior move is harder than one with many
     * equivalent choices. Increase dispersion without imposing a hard CPL cap. */
    if(found>1 && lines[0].score-lines[1].score>100 && legal->count>8)
        temperature*=1.0+fmin(.45,(lines[0].score-lines[1].score-100)/400.0);
    int selected=-1;
    if(temperature<=0.0) {
        for(int i=0;i<found;++i) if((!filter_unsafe||!unsafe[i]) &&
            (selected<0||lines[i].score>lines[selected].score)) selected=i;
    } else {
        int maximum=-MATE_SCORE;
        for(int i=0;i<found;++i) if((!filter_unsafe||!unsafe[i])&&lines[i].score>maximum)maximum=lines[i].score;
        double weights[16],total=0.0;
        for(int i=0;i<found;++i) {
            if(filter_unsafe&&unsafe[i])weights[i]=0.0;
            else {
                double exponent=(lines[i].score-maximum)/temperature;
                if(exponent < -60.0) exponent=-60.0;
                weights[i]=exp(exponent)*gui_human_move_weight(position,lines[i].move,strength_control);
                total+=weights[i];
            }
        }
        double draw=gui_random_unit()*total;
        for(int i=0;i<found;++i){draw-=weights[i];if(draw<=0.0){selected=i;break;}}
    }
    if(selected<0)selected=0;
    printf("Reduced strength %d (calibrated control %.1f): %s, clock %.2f s, useful search %.2f s, MultiPV %d, temperature %.1f cp, selected rank %d, legal %d, pieces %d%s\n",
           requested_elo,strength_control,state_name,move_time,search_budget,p.multipv,temperature,selected+1,legal->count,pieces,
           filter_unsafe?", mate awareness active":"");
    print_search_result(&lines[selected]); *out=lines[selected].move;

wait_and_return:
    {
        double remaining=move_time-(timer_seconds()-started);
        if(move_time<3600.0 && remaining>0.0) Sleep((DWORD)(remaining*1000.0));
    }
    return true;
}
/* Accepted releases available through the saved-engine selector. */
static const GuiEngineOption gui_engine_options[] = {
    {"1.0", L"1.0  (~1563 Elo)"}, {"1.1", L"1.1  (~1646 Elo)"},
    {"1.2", L"1.2  (~1650 Elo)"}, {"1.3", L"1.3  (~1678 Elo)"},
    {"1.4", L"1.4  (~1705 Elo)"}, {"1.5", L"1.5  (~1732 Elo)"},
    {"1.6", L"1.6  (~1745 Elo)"}, {"1.7", L"1.7  (~1775 Elo)"},
    {"1.7.1", L"1.7.1  (~1775 Elo)"}, {"2.0", L"2.0  (~1800 Elo)"},
    {"2.1", L"2.1  (~1840 Elo)"}, {"2.2", L"2.2  (~1865 Elo)"},
    {"2.3", L"2.3  (~1935 Elo)"}, {"3.0", L"3.0  (~1995 Elo)"},
    {"3.1", L"3.1  (~2145 Elo)"}, {"3.2", L"3.2  (~2185 Elo)"},
    {"3.3", L"3.3  (~2250 Elo)"}, {"3.4", L"3.4  (~2270 Elo)"},
    {"3.5", L"3.5  (~2295 Elo)"}, {"4.0", L"4.0  (~2320 Elo)"},
    {"4.1", L"4.1  (~2445 Elo)"}, {"5.0", L"5.0  (~2615 Elo)"},
    {"5.1", L"5.1  (~2660 Elo)"}, {"5.2", L"5.2  (~2680 Elo)"},
    {"5.3", L"5.3  (~2695 Elo)"}, {"5.4", L"5.4  (~2715 Elo)"},
    {"5.5", L"5.5  (~2728 Elo)"}, {"5.6", L"5.6  (~2801 Elo)"},
    {"5.7", L"5.7  (~2811 Elo)"}, {"6.0", L"6.0  (~2750 Elo)"},
    {"6.1", L"6.1  (~2763 Elo)"}, {"6.2", L"6.2  (~2790 Elo)"},
    {"6.3", L"6.3  (~2808 Elo)"}, {"6.4", L"6.4  (~2808 Elo)"},
    {"7.0", L"7.0  (~3000 Elo, 8 threads)"},
    {"7.1", L"7.1  (~3040 Elo, 16 threads)"},
    {"7.2", L"7.2  (~3060 Elo, 16 threads)"},
    {"7.3", L"7.3  (~3075 Elo, 16 threads)"},
    {"8.0", L"8.0  (NNUE, 16 threads)"},
    {"8.1", L"8.1  (~3257 Elo, 16 threads)"},
    {"8.2", L"8.2  (~3287 Elo, 16 threads)"},
    {"8.3", L"8.3  (full-data NNUE-256, 16 threads)"}
};
static void gui_load_piece_images(void) {
    static const wchar_t *names[13] = {
        NULL,
        L"white_pawn_modern_256x256.png", L"white_knight_modern_256x256.png",
        L"white_bishop_modern_256x256.png", L"white_rook_modern_256x256.png",
        L"white_queen_modern_256x256.png", L"white_king_modern_256x256.png",
        L"black_pawn_modern_256x256.png", L"black_knight_modern_256x256.png",
        L"black_bishop_modern_256x256.png", L"black_rook_modern_256x256.png",
        L"black_queen_modern_256x256.png", L"black_king_modern_256x256.png"
    };
    wchar_t module[MAX_PATH];
    DWORD length = GetModuleFileNameW(NULL, module, MAX_PATH);
    if (length == 0 || length >= MAX_PATH) return;
    wchar_t *separator = wcsrchr(module, L'\\');
    if (!separator) return;
    separator[1] = L'\0';

    for (int piece = WP; piece <= BK; ++piece) {
        wchar_t path[MAX_PATH];
        if (swprintf(path, MAX_PATH, L"%lsassets\\%ls", module,
                     names[piece]) < 0)
            continue;
        if (GdipLoadImageFromFile(path, &gui_piece_images[piece]) != 0)
            gui_piece_images[piece] = NULL;
    }
}

static void gui_release_piece_images(void) {
    for (int piece = WP; piece <= BK; ++piece) {
        if (gui_piece_images[piece]) {
            GdipDisposeImage(gui_piece_images[piece]);
            gui_piece_images[piece] = NULL;
        }
    }
}

static const wchar_t *gui_piece_glyph(Piece piece) {
    static const wchar_t *glyphs[] = {
        L"", L"♙", L"♘", L"♗", L"♖", L"♕", L"♔",
        L"♟", L"♞", L"♝", L"♜", L"♛", L"♚"
    };
    return glyphs[piece];
}

static double gui_clock_value(Color side) {
    if (gui.unlimited_clock[side]) return 0.0;
    double value = gui.remaining[side];
    if (gui.clock_started && !gui.game_over &&
        gui.position.side_to_move == side)
        value -= timer_seconds() - gui.turn_started;
    return value > 0.0 ? value : 0.0;
}

static void gui_print_final_pgn_if_needed(void) {
    if (!gui.game_over || gui.final_pgn_printed) return;
    printf("\nFinal PGN:\n");
    printf("[GUIBuild \"%s\"]\n", GUI_CANDIDATE_REVISION);
    printf("[GUISeedPolicy \"per-decision-main-stream-v1\"]\n");
    printf("[GUIStartupSeed \"%u\"]\n", gui_startup_seed);
    printf("[GUIFirstDecisionIndex \"%u\"]\n", gui_game_first_decision_index);
    printf("[WhiteTimeControl \"%.0f+%.0f\"]\n", gui.base_seconds[WHITE], gui.increment_seconds[WHITE]);
    printf("[BlackTimeControl \"%.0f+%.0f\"]\n", gui.base_seconds[BLACK], gui.increment_seconds[BLACK]);
    (void)write_pgn(stdout, &gui.game, &gui.position);
    fflush(stdout);
    gui.final_pgn_printed = true;
}

static void gui_time_loss(Color loser) {
    snprintf(gui.status, sizeof(gui.status), "%s loses on time — %s wins",
             color_name(loser), color_name(opposite(loser)));
    gui.remaining[loser] = 0.0;
    gui.game_over = true;
    snprintf(gui.game.forced_result, sizeof(gui.game.forced_result), "%s",
             loser == WHITE ? "0-1" : "1-0");
    gui_print_final_pgn_if_needed();
}

static bool gui_finish_clock_for_move(Color mover) {
    if (gui.unlimited_clock[mover]) {
        /* An unlimited White still starts Black's timed clock after the first
         * move. Every unlimited move also establishes the next turn's start. */
        if (!gui.clock_started) gui.clock_started = true;
        gui.turn_started = timer_seconds();
        return true;
    }
    /* Neither clock runs in the untouched starting position. White's first
     * completed move starts Black's clock and still earns White's increment. */
    if (!gui.clock_started) {
        gui.remaining[mover] += gui.increment_seconds[mover];
        gui.clock_started = true;
        gui.turn_started = timer_seconds();
        return true;
    }
    gui.remaining[mover] = gui_clock_value(mover);
    if (gui.remaining[mover] <= 0.0) {
        gui_time_loss(mover);
        return false;
    }
    gui.remaining[mover] += gui.increment_seconds[mover];
    gui.turn_started = timer_seconds();
    return true;
}

static void gui_refresh_status(void) {
    MoveList legal;
    generate_legal_moves(&gui.position, &legal);
    gui.game_over = false;
    if (legal.count == 0) {
        if (side_in_check(&gui.position, gui.position.side_to_move))
            snprintf(gui.status, sizeof(gui.status), "Checkmate — %s wins",
                     color_name(opposite(gui.position.side_to_move)));
        else
            snprintf(gui.status, sizeof(gui.status), "Draw by stalemate");
        gui.game_over = true;
    } else if (gui.position.halfmove_clock >= 100) {
        snprintf(gui.status, sizeof(gui.status), "Draw by the 50-move rule");
        gui.game_over = true;
    } else if (threefold_repetition(&gui.position)) {
        snprintf(gui.status, sizeof(gui.status), "Draw by threefold repetition");
        gui.game_over = true;
    } else if (insufficient_material(&gui.position)) {
        snprintf(gui.status, sizeof(gui.status), "Draw by insufficient material");
        gui.game_over = true;
    } else {
        snprintf(gui.status, sizeof(gui.status), "%s to move%s",
                 color_name(gui.position.side_to_move),
                 side_in_check(&gui.position, gui.position.side_to_move) ?
                 " — check" : "");
    }
    gui_print_final_pgn_if_needed();
}

/* Display recognition is independent of whether book play is enabled
 * or the current position has book continuations. Retain the latest named
 * position reached in the actual game, including transpositions. */
static bool gui_opening_name_from_history(const Position *position,
                                         char *out, size_t cap) {
    for (int h = position->history_count - 1; h >= 0; --h)
        for (int i = 0; i < opening_name_count; ++i)
            if (opening_names[i].position_key == position->position_history[h]) {
                snprintf(out, cap, "%s %s", opening_names[i].eco, opening_names[i].name);
                return true;
            }
    return false;
}

static void gui_refresh_opening(void) {
    char name[256];
    if (gui_opening_name_from_history(&gui.position, name, sizeof(name)))
        snprintf(gui.opening, sizeof(gui.opening), "%s", name);
    else
        snprintf(gui.opening, sizeof(gui.opening), "%s",
                 opening_name_count ? "No named opening yet" : "Opening names unavailable");
}

static void gui_new_game(HWND window, GuiPlayMode mode, Color human_side) {
    if(atomic_load(&gui_search_running)){MessageBeep(MB_ICONINFORMATION);return;}
    init_position(&gui.position);
    game_record_reset(&gui.game, &gui.position, false);
    gui.mode = mode;
    gui.human_side = human_side;
    gui.selected_square = -1;
    gui.last_from_square = -1;
    gui.last_to_square = -1;
    gui.final_pgn_printed = false;
    gui_game_first_decision_index = gui_decision_index + 1;
    for (int side = WHITE; side <= BLACK; ++side) {
        gui.strength_state[side] = GUI_STATE_NORMAL;
        gui.strength_state_remaining[side] = 0;
    }
    gui.remaining[WHITE] = gui.base_seconds[WHITE];
    gui.remaining[BLACK] = gui.base_seconds[BLACK];
    gui.clock_started = false;
    gui.turn_started = timer_seconds();
    char engine_player[2][96];
    for (int side = WHITE; side <= BLACK; ++side) {
        if (strcmp(gui.engine_version, ENGINE_VERSION) == 0) {
            if (gui.maximum_strength[side])
                snprintf(engine_player[side], sizeof(engine_player[side]),
                         "Engine %s (Maximum)", gui.engine_version);
            else
                snprintf(engine_player[side], sizeof(engine_player[side]),
                         "Engine %s (%d strength)", gui.engine_version,
                         gui.strength_elo[side]);
        } else {
            snprintf(engine_player[side], sizeof(engine_player[side]),
                     "Engine %s", gui.engine_version);
        }
    }
    if (mode == GUI_HUMAN_VS_HUMAN)
        game_record_set_players(&gui.game, "Human", "Human");
    else if (mode == GUI_ENGINE_VS_ENGINE)
        game_record_set_players(&gui.game, engine_player[WHITE],
                                engine_player[BLACK]);
    else if (human_side == WHITE)
        game_record_set_players(&gui.game, "Human", engine_player[BLACK]);
    else
        game_record_set_players(&gui.game, engine_player[WHITE], "Human");
    gui_refresh_status();
    snprintf(gui.opening, sizeof(gui.opening), "Not yet classified");
    gui_refresh_opening();
    InvalidateRect(window, NULL, TRUE);
    if (mode == GUI_ENGINE_VS_ENGINE ||
        (mode == GUI_HUMAN_VS_ENGINE && human_side == BLACK))
        gui_schedule_engine_if_needed(window);
}

static bool gui_is_human_turn(void) {
    return gui.mode == GUI_HUMAN_VS_HUMAN ||
           (gui.mode == GUI_HUMAN_VS_ENGINE &&
            gui.position.side_to_move == gui.human_side);
}

static unsigned __stdcall gui_search_worker(void *argument) {
    GuiSearchJob *job=(GuiSearchJob *)argument;
    srand(job->random_seed);
    printf("GUI decision %u: seed %u, build %s\n",
           job->decision_index, job->random_seed, GUI_CANDIDATE_REVISION);
    if(job->selected_current) {
        if(job->maximum_strength) {
            int prior_threads=search_thread_count;
            search_thread_count=16;
            job->found=choose_bot_move_with_budget(&job->position,&job->legal,
                BOT_ENGINE,job->max_depth,job->budget,&job->move);
            search_thread_count=prior_threads;
        } else {
            job->found=gui_choose_reduced_strength_move(&job->position,&job->legal,
                job->max_depth,job->budget,job->requested_elo,&job->move);
        }
    } else {
        job->found=tournament_version_move(job->engine_version,&job->position,
            job->base,job->increment,job->max_depth,&job->move);
    }
    if(atomic_load(&gui_window_closing)||
       !PostMessageW(job->window,GUI_ENGINE_RESULT_MESSAGE,0,(LPARAM)job)) {
        free(job);atomic_store(&gui_search_running,false);
    }
    return 0;
}

/* Start search asynchronously. The board snapshot belongs to the worker;
 * applying the result, clocks, PGN, and every HWND operation stay on the
 * window thread. */
static void gui_engine_move(HWND window) {
    if(gui.game_over||atomic_exchange(&gui_search_running,true))return;
    GuiSearchJob *job=calloc(1,sizeof *job);
    if(!job){atomic_store(&gui_search_running,false);return;}
    job->window=window;job->position=gui.position;job->mover=gui.position.side_to_move;
    generate_legal_moves(&job->position,&job->legal);
    job->selected_current=strcmp(gui.engine_version,ENGINE_VERSION)==0;
    job->maximum_strength=gui.maximum_strength[job->mover];
    job->unlimited=gui.unlimited_clock[job->mover];job->max_depth=gui.max_depth;
    job->requested_elo=gui.strength_elo[job->mover];
    job->random_seed=gui_next_search_seed();
    job->decision_index=++gui_decision_index;
    job->increment=gui.increment_seconds[job->mover];
    snprintf(job->engine_version,sizeof job->engine_version,"%s",gui.engine_version);
    if(job->selected_current) {
        job->budget=job->unlimited?86400.0:
            engine_time_budget(gui_clock_value(job->mover),job->increment)-gui.lag_reserve_seconds;
        if(job->budget<.001)job->budget=.001;
    } else {
        job->base=job->unlimited?1728000.0:gui_clock_value(job->mover)-20.0*gui.lag_reserve_seconds;
        if(job->base<.001)job->base=.001;
    }
    snprintf(gui.status,sizeof gui.status,"%s engine is thinking...",color_name(job->mover));
    InvalidateRect(window,NULL,FALSE);
    uintptr_t thread=_beginthreadex(NULL,0,gui_search_worker,job,0,NULL);
    if(!thread) {
        free(job);atomic_store(&gui_search_running,false);
        snprintf(gui.status,sizeof gui.status,"Could not start engine search");
        InvalidateRect(window,NULL,FALSE);return;
    }
    gui_search_thread=(HANDLE)thread;
}

static void gui_accept_engine_result(HWND window,GuiSearchJob *job) {
    if(gui_search_thread){CloseHandle(gui_search_thread);gui_search_thread=NULL;}
    atomic_store(&gui_search_running,false);
    bool current=!gui.game_over&&gui.position.zobrist_key==job->position.zobrist_key&&
                 gui.position.side_to_move==job->mover;
    if(!current||!job->found) {
        if(current){snprintf(gui.status,sizeof gui.status,"Engine search failed");InvalidateRect(window,NULL,FALSE);}
        free(job);return;
    }
    Move move=job->move;Color mover=job->mover;free(job);
    if(!gui_finish_clock_for_move(mover)){InvalidateRect(window,NULL,FALSE);return;}
    (void)game_record_move(&gui.game,&gui.position,move);
    gui.last_from_square=MOVE_FROM(move);gui.last_to_square=MOVE_TO(move);
    make_move(&gui.position,move);gui_refresh_opening();gui.selected_square=-1;
    gui_refresh_status();InvalidateRect(window,NULL,FALSE);gui_schedule_engine_if_needed(window);
}

static void gui_schedule_engine_if_needed(HWND window) {
    if (!gui.game_over && !atomic_load(&gui_search_running) &&
        (gui.mode == GUI_ENGINE_VS_ENGINE ||
         (gui.mode == GUI_HUMAN_VS_ENGINE &&
          gui.position.side_to_move != gui.human_side))) {
        /* Paint the completed move now, then queue the next engine turn. This
         * keeps engine-vs-engine animation visible without charging a fixed
         * 75 ms delay on every move. */
        PostMessageW(window, GUI_ENGINE_MOVE_MESSAGE, 0, 0);
    }
}

static bool gui_square_is_legal_target(int square, const MoveList *legal) {
    if (gui.selected_square < 0) return false;
    for (int i = 0; i < legal->count; ++i)
        if (MOVE_FROM(legal->moves[i]) == gui.selected_square &&
            MOVE_TO(legal->moves[i]) == square)
            return true;
    return false;
}

static void gui_try_board_click(HWND window, int square) {
    if (gui.game_over || !gui_is_human_turn()) return;
    Piece clicked = gui.position.board[square];
    Color side = gui.position.side_to_move;
    if (gui.selected_square < 0) {
        if (clicked != EMPTY && piece_color(clicked) == side)
            gui.selected_square = square;
        InvalidateRect(window, NULL, FALSE);
        return;
    }

    if (clicked != EMPTY && piece_color(clicked) == side) {
        gui.selected_square = square;
        InvalidateRect(window, NULL, FALSE);
        return;
    }

    MoveList legal;
    generate_legal_moves(&gui.position, &legal);
    Move chosen = encode_move(0, 0, MOVE_QUIET);
    bool found = false;
    for (int i = 0; i < legal.count; ++i) {
        Move candidate = legal.moves[i];
        if (MOVE_FROM(candidate) != gui.selected_square ||
            MOVE_TO(candidate) != square)
            continue;
        if (!found || promotion_char_from_flag(MOVE_FLAG(candidate)) == 'q') {
            chosen = candidate;
            found = true;
        }
    }
    if (!found) {
        gui.selected_square = -1;
        InvalidateRect(window, NULL, FALSE);
        return;
    }

    Color mover = gui.position.side_to_move;
    if (!gui_finish_clock_for_move(mover)) {
        InvalidateRect(window, NULL, TRUE);
        return;
    }
    (void)game_record_move(&gui.game, &gui.position, chosen);
    gui.last_from_square = MOVE_FROM(chosen);
    gui.last_to_square = MOVE_TO(chosen);
    make_move(&gui.position, chosen);
    gui_refresh_opening();
    gui.selected_square = -1;
    gui_refresh_status();
    InvalidateRect(window, NULL, TRUE);
    gui_schedule_engine_if_needed(window);
}

static void gui_draw_button(HDC dc, RECT rect, const wchar_t *text) {
    HBRUSH brush = CreateSolidBrush(RGB(73, 107, 47));
    HPEN pen = CreatePen(PS_SOLID, 1, RGB(93, 133, 63));
    HBRUSH previous_brush = (HBRUSH)SelectObject(dc, brush);
    HPEN previous_pen = (HPEN)SelectObject(dc, pen);
    RoundRect(dc, rect.left, rect.top, rect.right, rect.bottom, 8, 8);
    SelectObject(dc, previous_pen);
    SelectObject(dc, previous_brush);
    DeleteObject(pen);
    DeleteObject(brush);
    SetTextColor(dc, RGB(245, 245, 245));
    SetBkMode(dc, TRANSPARENT);
    DrawTextW(dc, text, -1, &rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

static bool gui_parse_strength_text(const wchar_t *text, int *value) {
    int count = 0, rating = 0;
    if (!text || !text[0]) return false;
    for (; text[count]; ++count) {
        if (count >= 4 || text[count] < L'0' || text[count] > L'9') return false;
        rating = rating * 10 + text[count] - L'0';
    }
    if (rating < 600 || rating > 2600) return false;
    *value = rating;
    return true;
}

/* Preview controls stay synchronized; actual strength changes only on Apply. */
static void gui_sync_strength_input(HWND window, int side, bool from_slider) {
    wchar_t text[32];
    if (from_slider) {
        int rating = (int)SendMessageW(gui_strength_slider[side], TBM_GETPOS, 0, 0);
        swprintf(text, 32, L"%d", rating);
        SetWindowTextW(gui_strength_edit[side], text);
    } else {
        int rating;
        GetWindowTextW(gui_strength_edit[side], text, 32);
        if (gui_parse_strength_text(text, &rating))
            SendMessageW(gui_strength_slider[side], TBM_SETPOS, TRUE, rating);
    }
    RECT panel = {0, 0, 900, 308};
    InvalidateRect(window, &panel, FALSE);
}

static void gui_apply_settings(HWND window) {
    if(atomic_load(&gui_search_running)){MessageBeep(MB_ICONINFORMATION);return;}
    wchar_t text[64];
    int requested_strength[2];
    for (int side = WHITE; side <= BLACK; ++side) {
        GetWindowTextW(gui_strength_edit[side], text, 64);
        if (!gui_parse_strength_text(text, &requested_strength[side])) {
            MessageBoxW(window, L"Enter a whole-number relative Elo from 600 to 2600 for each profile.",
                        L"Invalid Elo", MB_OK | MB_ICONWARNING);
            SetFocus(gui_strength_edit[side]);
            SendMessageW(gui_strength_edit[side], EM_SETSEL, 0, -1);
            return;
        }
    }
    wchar_t *end = NULL;
    double base[2] = {gui.base_seconds[WHITE], gui.base_seconds[BLACK]};
    double increment[2] = {gui.increment_seconds[WHITE],
                           gui.increment_seconds[BLACK]};
    bool unlimited[2];
    for (int side = WHITE; side <= BLACK; ++side)
        unlimited[side] = SendMessageW(gui_unlimited_check[side],
                                       BM_GETCHECK, 0, 0) == BST_CHECKED;
    for (int side = WHITE; side <= BLACK; ++side) {
        if (!unlimited[side]) {
            GetWindowTextW(gui_base_edit[side], text, 64);
            base[side] = wcstod(text, &end);
            if (end == text || *end != L'\0' || !(base[side] > 0.0) ||
                base[side] > 86400.0) {
                MessageBoxW(window, L"Each base time must be above 0 and no more "
                                    L"than 86400 seconds.",
                            L"Invalid clock", MB_OK | MB_ICONWARNING);
                return;
            }
            GetWindowTextW(gui_increment_edit[side], text, 64);
            increment[side] = wcstod(text, &end);
            if (end == text || *end != L'\0' || !(increment[side] >= 0.0) ||
                increment[side] > 3600.0) {
                MessageBoxW(window, L"Each increment must be from 0 to 3600 seconds.",
                            L"Invalid clock", MB_OK | MB_ICONWARNING);
                return;
            }
        }
    }
    GetWindowTextW(gui_depth_edit, text, 64);
    long depth = wcstol(text, &end, 10);
    if (end == text || *end != L'\0' || depth < 1 ||
        depth >= MAX_SEARCH_PLY) {
        MessageBoxW(window, L"Depth must be from 1 to 127.",
                    L"Invalid depth", MB_OK | MB_ICONWARNING);
        return;
    }
    GetWindowTextW(gui_threads_edit, text, 64);
    long threads = wcstol(text, &end, 10);
    if (end == text || *end != L'\0' || threads < 1 ||
        threads > MAX_SEARCH_THREADS) {
        MessageBoxW(window, L"Threads must be from 1 to 16.",
                    L"Invalid threads", MB_OK | MB_ICONWARNING);
        return;
    }
    GetWindowTextW(gui_lag_edit, text, 64);
    double lag_reserve = wcstod(text, &end);
    if (end == text || *end != L'\0' || !(lag_reserve >= 0.0) ||
        lag_reserve > 5.0) {
        MessageBoxW(window, L"Lag reserve must be from 0 to 5 seconds.",
                    L"Invalid lag reserve", MB_OK | MB_ICONWARNING);
        return;
    }
    gui.base_seconds[WHITE] = base[WHITE];
    gui.base_seconds[BLACK] = base[BLACK];
    gui.increment_seconds[WHITE] = increment[WHITE];
    gui.increment_seconds[BLACK] = increment[BLACK];
    gui.unlimited_clock[WHITE] = unlimited[WHITE];
    gui.unlimited_clock[BLACK] = unlimited[BLACK];
    LRESULT selected = SendMessageW(gui_engine_combo, CB_GETCURSEL, 0, 0);
    if (selected != CB_ERR) {
        LRESULT option = SendMessageW(gui_engine_combo, CB_GETITEMDATA,
                                      (WPARAM)selected, 0);
        if (option >= 0 && (size_t)option <
            sizeof(gui_engine_options) / sizeof(gui_engine_options[0]))
            snprintf(gui.engine_version, sizeof(gui.engine_version), "%s",
                     gui_engine_options[option].version);
    }
    for (int side = WHITE; side <= BLACK; ++side) {
        gui.strength_elo[side] = requested_strength[side];
        gui.maximum_strength[side] = SendMessageW(
            gui_strength_max_check[side], BM_GETCHECK, 0, 0) == BST_CHECKED;
        for(int skill=0;skill<GUI_SKILL_COUNT;++skill)
            gui.skill_elo[side][skill]=0;
    }
    gui.max_depth = (int)depth;
    /* Current reduced play overrides search threads per move: one for slider
     * strengths, sixteen for Maximum. This field remains the saved-version
     * worker count when a historical executable is selected. */
    gui.threads = (int)threads;
    search_thread_count = gui.threads;
    gui.lag_reserve_seconds = lag_reserve;
    gui.remaining[WHITE] = base[WHITE];
    gui.remaining[BLACK] = base[BLACK];
    gui.clock_started = gui.position.history_count > 1;
    gui.turn_started = timer_seconds();
    gui_refresh_status();
    InvalidateRect(window, NULL, FALSE);
    gui_schedule_engine_if_needed(window);
}

/* Run a saved-version match from the GUI. Progress and per-game totals are
 * also printed to the console; the final aggregate is shown in a dialog. */
static void gui_run_tournament(HWND window) {
    if(atomic_load(&gui_search_running)){MessageBeep(MB_ICONINFORMATION);return;}
    wchar_t wide_a[64], wide_b[64], wide_games[32], *end = NULL;
    char player_a[TOURNAMENT_MAX_NAME], player_b[TOURNAMENT_MAX_NAME];
    GetWindowTextW(gui_match_a_edit, wide_a, 64);
    GetWindowTextW(gui_match_b_edit, wide_b, 64);
    GetWindowTextW(gui_match_games_edit, wide_games, 32);
    WideCharToMultiByte(CP_UTF8, 0, wide_a, -1, player_a, sizeof(player_a), NULL, NULL);
    WideCharToMultiByte(CP_UTF8, 0, wide_b, -1, player_b, sizeof(player_b), NULL, NULL);
    long games = wcstol(wide_games, &end, 10);
    if (end == wide_games || *end != L'\0' || games < 1 || games > 100000) {
        MessageBoxW(window, L"Games must be from 1 to 100000.",
                    L"Invalid match", MB_OK | MB_ICONWARNING);
        return;
    }
    TournamentResult result;
    char running_title[128];
    snprintf(running_title, sizeof(running_title), "%s - match running",
             ENGINE_BUILD_NAME);
    SetWindowTextA(window, running_title);
    UpdateWindow(window);
    bool ok = run_tournament(player_a, player_b, (int)games,
                             gui.base_seconds[WHITE],
                             gui.increment_seconds[WHITE], gui.max_depth,
                             &result);
    SetWindowTextA(window, ENGINE_BUILD_NAME);
    if (!ok) {
        MessageBoxW(window, L"Match failed. Check the version names, saved "
                            L"executables, settings, and EPD file.",
                    L"Tournament", MB_OK | MB_ICONERROR);
        return;
    }
    wchar_t summary[512];
    swprintf(summary, 512,
             L"%hs: %d wins\n%hs: %d wins\nDraws: %d\nErrors: %d",
             result.player_a, result.a_wins, result.player_b, result.b_wins,
             result.draws, result.errors);
    MessageBoxW(window, summary, L"Tournament results", MB_OK | MB_ICONINFORMATION);
}

static void gui_format_clock(Color side, double seconds, wchar_t out[32]) {
    if (gui.unlimited_clock[side]) {
        swprintf(out, 32, L"Unlimited");
        return;
    }
    if (seconds < 0.0) seconds = 0.0;
    int minutes = (int)(seconds / 60.0);
    double remainder = seconds - minutes * 60.0;
    swprintf(out, 32, L"%d:%04.1f", minutes, remainder);
}

static void gui_paint(HWND window) {
    PAINTSTRUCT paint;
    HDC window_dc = BeginPaint(window, &paint);
    RECT client;
    GetClientRect(window, &client);
    int client_width = client.right > 0 ? client.right : 1;
    int client_height = client.bottom > 0 ? client.bottom : 1;

    /* Compose the entire frame in memory. The clock invalidates the window ten
     * times per second; presenting one finished bitmap avoids visible partial
     * clears, board squares, and piece-image draws. */
    HDC dc = CreateCompatibleDC(window_dc);
    HBITMAP frame = CreateCompatibleBitmap(window_dc, client_width,
                                           client_height);
    HBITMAP previous_frame = (HBITMAP)SelectObject(dc, frame);
    HBRUSH background = CreateSolidBrush(RGB(38, 37, 34));
    FillRect(dc, &client, background);
    DeleteObject(background);

    int available_width = client.right - 24;
    int available_height = client.bottom - 436;
    gui.square_size = available_width / 8;
    if (available_height / 8 < gui.square_size)
        gui.square_size = available_height / 8;
    if (gui.square_size < 32) gui.square_size = 32;
    gui.board_x = (client.right - gui.square_size * 8) / 2;
    gui.board_y = 310;

    RECT board_shadow = {gui.board_x + 6, gui.board_y + 7,
                         gui.board_x + gui.square_size * 8 + 6,
                         gui.board_y + gui.square_size * 8 + 7};
    HBRUSH shadow_brush = CreateSolidBrush(RGB(20, 19, 18));
    FillRect(dc, &board_shadow, shadow_brush);
    DeleteObject(shadow_brush);

    SetTextColor(dc, RGB(235, 235, 235));
    SetBkMode(dc, TRANSPARENT);
    static const wchar_t *panel_names[]={L"Play",L"Settings",L"Strength",L"Match"};
    for(int i=0;i<4;++i) {
        RECT tab={12+i*142,10,144+i*142,43};
        gui_draw_button(dc,tab,panel_names[i]);
        if(i==gui_active_panel){HPEN pen=CreatePen(PS_SOLID,3,RGB(129,182,76));
            HPEN old=(HPEN)SelectObject(dc,pen);MoveToEx(dc,tab.left+8,tab.bottom-2,NULL);
            LineTo(dc,tab.right-8,tab.bottom-2);SelectObject(dc,old);DeleteObject(pen);}
    }
    RECT flip_button = {640, 10, 782, 43};
    gui_draw_button(dc, flip_button, L"Flip Board");
    if(gui_active_panel==GUI_PANEL_PLAY) {
        RECT buttons[5]={{12,62,164,98},{174,62,306,98},{316,62,448,98},
                         {458,62,630,98},{640,62,782,98}};
        gui_draw_button(dc,buttons[0],L"Human vs Human");
        gui_draw_button(dc,buttons[1],L"Play White");
        gui_draw_button(dc,buttons[2],L"Play Black");
        gui_draw_button(dc,buttons[3],L"Engine vs Engine");
        gui_draw_button(dc,buttons[4],L"Engine Move");
        const wchar_t *hint=L"Choose a game mode. Detailed controls are kept in the other panels.";
        TextOutW(dc,12,122,hint,(int)wcslen(hint));
    } else if(gui_active_panel==GUI_PANEL_SETTINGS) {
        TextOutW(dc,12,66,L"White base",10);TextOutW(dc,178,66,L"Increment",9);
        TextOutW(dc,344,66,L"Black base",10);TextOutW(dc,510,66,L"Increment",9);
        TextOutW(dc,12,125,L"Engine version",14);TextOutW(dc,344,125,L"Depth",5);
        TextOutW(dc,474,125,L"Threads",7);TextOutW(dc,604,125,L"Lag reserve",11);
        RECT apply_button={730,118,820,151};gui_draw_button(dc,apply_button,L"Apply");
    } else if(gui_active_panel==GUI_PANEL_STRENGTH) {
        for(int side=WHITE;side<=BLACK;++side) {
            int x=side==WHITE?12:452;
            TextOutW(dc,x,52,side==WHITE?L"WHITE PROFILE":L"BLACK PROFILE",13);
            int overall=(int)SendMessageW(gui_strength_slider[side],TBM_GETPOS,0,0);
            int low,high;gui_relative_fit_interval(overall,&low,&high);
            wchar_t range[64];
            if (SendMessageW(gui_strength_max_check[side],BM_GETCHECK,0,0)==BST_CHECKED)
                swprintf(range,64,L"Maximum: outside fitted range");
            else if (overall==1500)
                swprintf(range,64,L"1500: fixed relative reference");
            else
                swprintf(range,64,L"Fit 95%%: %d-%d (relative)",low,high);
            TextOutW(dc,x+145,52,range,(int)wcslen(range));
            TextOutW(dc,x,82,L"Target",6);
        }
        const wchar_t *hint=L"Fit 95%: relative sampling uncertainty only. Chess.com calibration pending.";
        TextOutW(dc,12,148,hint,(int)wcslen(hint));
        const wchar_t *entry_hint=L"Type 600-2600 or move the slider, then click Apply.";
        TextOutW(dc,12,180,entry_hint,(int)wcslen(entry_hint));
        RECT apply_profile={700,174,825,206};gui_draw_button(dc,apply_profile,L"Apply");
    } else {
        TextOutW(dc,12,70,L"Engine A",8);TextOutW(dc,286,70,L"Engine B",8);
        TextOutW(dc,560,70,L"Games",5);
        RECT match_button={700,62,825,96};gui_draw_button(dc,match_button,L"Run Match");
        const wchar_t *hint=L"Tournament output and aggregate statistics are printed to the terminal.";
        TextOutW(dc,12,120,hint,(int)wcslen(hint));
    }

    HFONT piece_font = CreateFontW(
        (int)(gui.square_size * 0.72), 0, 0, 0, FW_NORMAL, FALSE, FALSE,
        FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        ANTIALIASED_QUALITY, DEFAULT_PITCH, L"Segoe UI Symbol");
    HFONT old_font = (HFONT)SelectObject(dc, piece_font);
    GpGraphics *graphics = NULL;
    (void)GdipCreateFromHDC(dc, &graphics);
    if (graphics) (void)GdipSetInterpolationMode(graphics, 7);
    HFONT coordinate_font = CreateFontW(
        gui.square_size > 56 ? 12 : 10, 0, 0, 0, FW_BOLD, FALSE, FALSE,
        FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        ANTIALIASED_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    MoveList legal;
    generate_legal_moves(&gui.position, &legal);

    for (int display_rank = 0; display_rank < 8; ++display_rank) {
        for (int display_file = 0; display_file < 8; ++display_file) {
            int square = gui_display_square(display_file, display_rank);
            int file = square % 8;
            int rank = square / 8;
            RECT cell = {
                gui.board_x + display_file * gui.square_size,
                gui.board_y + display_rank * gui.square_size,
                gui.board_x + (display_file + 1) * gui.square_size,
                gui.board_y + (display_rank + 1) * gui.square_size
            };
            /* a1 is dark in standard chessboard orientation. */
            bool light_square = ((file + rank) & 1) != 0;
            COLORREF color = light_square ? RGB(238, 238, 210) :
                                            RGB(118, 150, 86);
            if (square == gui.last_from_square || square == gui.last_to_square)
                color = light_square ? RGB(245, 246, 130) : RGB(186, 202, 68);
            if (square == gui.selected_square)
                color = light_square ? RGB(246, 246, 105) : RGB(191, 203, 68);
            HBRUSH cell_brush = CreateSolidBrush(color);
            FillRect(dc, &cell, cell_brush);
            DeleteObject(cell_brush);

            if (gui_square_is_legal_target(square, &legal)) {
                int radius = gui.square_size / 9;
                int cx = (cell.left + cell.right) / 2;
                int cy = (cell.top + cell.bottom) / 2;
                HBRUSH dot = CreateSolidBrush(RGB(70, 110, 65));
                HBRUSH previous = (HBRUSH)SelectObject(dc, dot);
                Ellipse(dc, cx - radius, cy - radius, cx + radius, cy + radius);
                SelectObject(dc, previous);
                DeleteObject(dot);
            }

            Piece piece = gui.position.board[square];
            if (piece != EMPTY) {
                if (graphics && gui_piece_images[piece]) {
                    int margin = gui.square_size / 16;
                    GdipDrawImageRectI(graphics, gui_piece_images[piece],
                                       cell.left + margin, cell.top + margin,
                                       gui.square_size - 2 * margin,
                                       gui.square_size - 2 * margin);
                } else {
                    SetBkMode(dc, TRANSPARENT);
                    SetTextColor(dc, piece_color(piece) == WHITE ?
                                 RGB(250, 250, 250) : RGB(25, 25, 25));
                    DrawTextW(dc, gui_piece_glyph(piece), -1, &cell,
                              DT_CENTER | DT_VCENTER | DT_SINGLELINE);
                }
            }

            HFONT prior_font = (HFONT)SelectObject(dc, coordinate_font);
            SetTextColor(dc, light_square ? RGB(118, 150, 86) :
                                            RGB(238, 238, 210));
            SetBkMode(dc, TRANSPARENT);
            wchar_t coordinate[2] = {0, 0};
            if (display_rank == 7) {
                coordinate[0] = (wchar_t)(L'a' + file);
                TextOutW(dc, cell.right - 11, cell.bottom - 15, coordinate, 1);
            }
            if (display_file == 0) {
                coordinate[0] = (wchar_t)(L'1' + rank);
                TextOutW(dc, cell.left + 3, cell.top + 2, coordinate, 1);
            }
            SelectObject(dc, prior_font);
        }
    }
    DeleteObject(coordinate_font);
    if (graphics) GdipDeleteGraphics(graphics);
    SelectObject(dc, old_font);
    DeleteObject(piece_font);

    HFONT status_font = CreateFontW(20, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE,
                                    FALSE, DEFAULT_CHARSET, 0, 0,
                                    ANTIALIASED_QUALITY, 0, L"Segoe UI");
    old_font = (HFONT)SelectObject(dc, status_font);
    SetTextColor(dc, RGB(240, 240, 240));
    SetBkMode(dc, TRANSPARENT);
    wchar_t wide_status[256];
    MultiByteToWideChar(CP_UTF8, 0, gui.status, -1, wide_status, 256);
    wchar_t white_clock[32], black_clock[32], clocks[96];
    gui_format_clock(WHITE, gui_clock_value(WHITE), white_clock);
    gui_format_clock(BLACK, gui_clock_value(BLACK), black_clock);
    swprintf(clocks, 96, L"White  %ls     Black  %ls", white_clock, black_clock);
    RECT clock_rect = {12, gui.board_y + gui.square_size * 8 + 7,
                       client.right - 12, client.bottom - 8};
    DrawTextW(dc, clocks, -1, &clock_rect,
              DT_CENTER | DT_TOP | DT_SINGLELINE);
    RECT status_rect = {12, gui.board_y + gui.square_size * 8 + 32,
                        client.right - 12, client.bottom - 8};
    DrawTextW(dc, wide_status, -1, &status_rect,
              DT_CENTER | DT_TOP | DT_SINGLELINE);
    wchar_t opening_text[320];
    wchar_t wide_opening[256];
    MultiByteToWideChar(CP_UTF8, 0, gui.opening, -1, wide_opening, 256);
    swprintf(opening_text, 320, L"Opening (last recognized): %ls", wide_opening);
    RECT opening_rect = {12, gui.board_y + gui.square_size * 8 + 57,
                         client.right - 12, client.bottom - 8};
    DrawTextW(dc, opening_text, -1, &opening_rect,
              DT_CENTER | DT_TOP | DT_SINGLELINE | DT_END_ELLIPSIS);
    SelectObject(dc, old_font);
    DeleteObject(status_font);
    BitBlt(window_dc, 0, 0, client_width, client_height, dc, 0, 0, SRCCOPY);
    SelectObject(dc, previous_frame);
    DeleteObject(frame);
    DeleteDC(dc);
    EndPaint(window, &paint);
}

static LRESULT CALLBACK chess_window_proc(HWND window, UINT message,
                                          WPARAM wparam, LPARAM lparam) {
    switch (message) {
        case WM_CREATE: {
            gui_control_brush=CreateSolidBrush(RGB(52,51,48));
            gui_ui_font=CreateFontW(16,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,
                DEFAULT_CHARSET,OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY,DEFAULT_PITCH,L"Segoe UI");
            gui_base_edit[WHITE] = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 92, 60, 72, 30, window, NULL, NULL, NULL);
            gui_increment_edit[WHITE] = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 258, 60, 72, 30, window, NULL, NULL, NULL);
            gui_base_edit[BLACK] = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 424, 60, 72, 30, window, NULL, NULL, NULL);
            gui_increment_edit[BLACK] = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 590, 60, 72, 30, window, NULL, NULL, NULL);
            gui_depth_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 390, 120, 62, 30, window, NULL, NULL, NULL);
            gui_match_a_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"1.0", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 85, 62, 180, 30, window, NULL, NULL, NULL);
            gui_match_b_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"random", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 359, 62, 180, 30, window, NULL, NULL, NULL);
            gui_match_games_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"10", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 610, 62, 72, 30, window, NULL, NULL, NULL);
            gui_lag_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"0.01", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 682, 120, 70, 30, window, NULL, NULL, NULL);
            gui_engine_combo = CreateWindowExW(
                0, L"COMBOBOX", L"", WS_CHILD | WS_VISIBLE | WS_VSCROLL |
                CBS_DROPDOWNLIST, 125, 120, 200, 360,
                window, NULL, NULL, NULL);
            gui_strength_slider[WHITE] = CreateWindowExW(
                0, TRACKBAR_CLASSW, L"", WS_CHILD | WS_VISIBLE |
                TBS_HORZ | TBS_NOTICKS, 90, 72, 260, 30,
                window, NULL, NULL, NULL);
            gui_strength_slider[BLACK] = CreateWindowExW(
                0, TRACKBAR_CLASSW, L"", WS_CHILD | WS_VISIBLE |
                TBS_HORZ | TBS_NOTICKS, 530, 72, 260, 30,
                window, NULL, NULL, NULL);
            for (int side = WHITE; side <= BLACK; ++side) {
                SendMessageW(gui_strength_slider[side], TBM_SETRANGE, TRUE,
                             MAKELPARAM(600, 2600));
                SendMessageW(gui_strength_slider[side], TBM_SETPAGESIZE, 0, 100);
                SendMessageW(gui_strength_slider[side], TBM_SETLINESIZE, 0, 1);
                SendMessageW(gui_strength_slider[side], TBM_SETPOS, TRUE,
                             gui.strength_elo[side]);
                gui_strength_edit[side] = CreateWindowExW(
                    WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                    ES_AUTOHSCROLL | ES_NUMBER, side == WHITE ? 366 : 806, 72, 70, 30,
                    window, (HMENU)(INT_PTR)(1004 + side), NULL, NULL);
                SendMessageW(gui_strength_edit[side], EM_SETLIMITTEXT, 4, 0);
                wchar_t rating_text[16];
                swprintf(rating_text, 16, L"%d", gui.strength_elo[side]);
                SetWindowTextW(gui_strength_edit[side], rating_text);
            }
            gui_strength_max_check[WHITE] = CreateWindowExW(
                0, L"BUTTON", L"Maximum", WS_CHILD | WS_VISIBLE |
                BS_AUTOCHECKBOX, 290, 112, 100, 25,
                window, (HMENU)(INT_PTR)1002, NULL, NULL);
            gui_strength_max_check[BLACK] = CreateWindowExW(
                0, L"BUTTON", L"Maximum", WS_CHILD | WS_VISIBLE |
                BS_AUTOCHECKBOX, 730, 112, 100, 25,
                window, (HMENU)(INT_PTR)1003, NULL, NULL);
            for (int side = WHITE; side <= BLACK; ++side)
                SendMessageW(gui_strength_max_check[side], BM_SETCHECK,
                             gui.maximum_strength[side] ? BST_CHECKED :
                             BST_UNCHECKED, 0);
            gui_threads_edit = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                ES_AUTOHSCROLL, 530, 120, 58, 30,
                window, NULL, NULL, NULL);
            gui_unlimited_check[WHITE] = CreateWindowExW(
                0, L"BUTTON", L"White unlimited", WS_CHILD | WS_VISIBLE |
                BS_AUTOCHECKBOX, 12, 174, 140, 26,
                window, NULL, NULL, NULL);
            gui_unlimited_check[BLACK] = CreateWindowExW(
                0, L"BUTTON", L"Black unlimited", WS_CHILD | WS_VISIBLE |
                BS_AUTOCHECKBOX, 160, 174, 140, 26,
                window, NULL, NULL, NULL);
            gui_nnue_check = CreateWindowExW(
                0, L"BUTTON", L"Use NNUE", WS_CHILD | WS_VISIBLE |
                BS_AUTOCHECKBOX, 320, 174, 112, 26,
                window, (HMENU)(INT_PTR)1001, NULL, NULL);
            SendMessageW(gui_nnue_check, BM_SETCHECK,
                         nnue_enabled ? BST_CHECKED : BST_UNCHECKED, 0);
            int default_engine = 0;
            for (size_t i = 0; i < sizeof(gui_engine_options) /
                                      sizeof(gui_engine_options[0]); ++i) {
                LRESULT item = SendMessageW(gui_engine_combo, CB_ADDSTRING, 0,
                                            (LPARAM)gui_engine_options[i].label);
                if (item != CB_ERR && item != CB_ERRSPACE)
                    SendMessageW(gui_engine_combo, CB_SETITEMDATA,
                                 (WPARAM)item, (LPARAM)i);
                if (strcmp(gui_engine_options[i].version, ENGINE_VERSION) == 0)
                    default_engine = (int)i;
            }
            SendMessageW(gui_engine_combo, CB_SETCURSEL,
                         (WPARAM)default_engine, 0);
            wchar_t value[64];
            for (int side = WHITE; side <= BLACK; ++side) {
                swprintf(value, 64, L"%.1f", gui.base_seconds[side]);
                SetWindowTextW(gui_base_edit[side], value);
                swprintf(value, 64, L"%.1f", gui.increment_seconds[side]);
                SetWindowTextW(gui_increment_edit[side], value);
            }
            swprintf(value, 64, L"%d", gui.max_depth);
            SetWindowTextW(gui_depth_edit, value);
            swprintf(value, 64, L"%d", gui.threads);
            SetWindowTextW(gui_threads_edit, value);
            for(int side=WHITE;side<=BLACK;++side) {
                gui_theme_control(gui_base_edit[side]);gui_theme_control(gui_increment_edit[side]);
                gui_theme_control(gui_unlimited_check[side]);gui_theme_control(gui_strength_slider[side]);
                gui_theme_control(gui_strength_max_check[side]);
                gui_theme_control(gui_strength_edit[side]);
            }
            gui_theme_control(gui_depth_edit);gui_theme_control(gui_threads_edit);
            gui_theme_control(gui_lag_edit);gui_theme_control(gui_engine_combo);
            gui_theme_control(gui_nnue_check);gui_theme_control(gui_match_a_edit);
            gui_theme_control(gui_match_b_edit);gui_theme_control(gui_match_games_edit);
            gui_update_panel_visibility();
            SetTimer(window, 2, 100, NULL);
            return 0;
        }
        case WM_PAINT:
            gui_paint(window);
            return 0;
        case WM_ERASEBKGND:
            /* gui_paint() fills every pixel in its off-screen frame. */
            return 1;
        case WM_CTLCOLOREDIT:
        case WM_CTLCOLORLISTBOX:
        case WM_CTLCOLORSTATIC: {
            HDC control_dc=(HDC)wparam;
            SetTextColor(control_dc,RGB(238,238,238));
            SetBkColor(control_dc,RGB(52,51,48));
            SetBkMode(control_dc,OPAQUE);
            return (LRESULT)gui_control_brush;
        }
        case WM_HSCROLL:
            for (int side = WHITE; side <= BLACK; ++side)
                if ((HWND)lparam == gui_strength_slider[side])
                    gui_sync_strength_input(window, side, true);
            return 0;
        case WM_COMMAND:
            if ((LOWORD(wparam) == 1004 || LOWORD(wparam) == 1005) &&
                HIWORD(wparam) == EN_CHANGE) {
                gui_sync_strength_input(window, LOWORD(wparam) - 1004, false);
                return 0;
            }
            if ((LOWORD(wparam) == 1002 || LOWORD(wparam) == 1003) &&
                HIWORD(wparam) == BN_CLICKED) {
                InvalidateRect(window, NULL, FALSE);
                return 0;
            }
            if (LOWORD(wparam) == 1001 && HIWORD(wparam) == BN_CLICKED) {
                bool requested = SendMessageW(gui_nnue_check, BM_GETCHECK, 0, 0)
                                 == BST_CHECKED;
                if (requested && nnue_hidden == 0) {
                    SendMessageW(gui_nnue_check, BM_SETCHECK, BST_UNCHECKED, 0);
                    MessageBoxW(window,
                                L"The default NNUE network could not be loaded.",
                                L"NNUE unavailable", MB_OK | MB_ICONWARNING);
                } else {
                    nnue_enabled = requested;
                    tt_clear();
                    snprintf(gui.status, sizeof gui.status, "%s evaluation enabled",
                             nnue_enabled ? "NNUE" : "Classical");
                    InvalidateRect(window, NULL, FALSE);
                }
                return 0;
            }
            return DefWindowProcW(window, message, wparam, lparam);
        case WM_LBUTTONDOWN: {
            int x = (short)LOWORD(lparam);
            int y = (short)HIWORD(lparam);
            if (y >= 10 && y <= 43 && x >= 640 && x <= 782) {
                gui_board_flipped = !gui_board_flipped;
                InvalidateRect(window, NULL, FALSE);
                return 0;
            }
            if(y>=10&&y<=43&&x>=12&&x<580) {
                gui_active_panel=(x-12)/142;
                if(gui_active_panel>GUI_PANEL_MATCH)gui_active_panel=GUI_PANEL_MATCH;
                gui_update_panel_visibility();InvalidateRect(window,NULL,FALSE);return 0;
            }
            if (gui_active_panel==GUI_PANEL_PLAY&&y >= 62 && y <= 98) {
                if (x >= 12 && x <= 164)
                    gui_new_game(window, GUI_HUMAN_VS_HUMAN, WHITE);
                else if (x >= 174 && x <= 306)
                    gui_new_game(window, GUI_HUMAN_VS_ENGINE, WHITE);
                else if (x >= 316 && x <= 448)
                    gui_new_game(window, GUI_HUMAN_VS_ENGINE, BLACK);
                else if (x >= 458 && x <= 630)
                    gui_new_game(window, GUI_ENGINE_VS_ENGINE, WHITE);
                else if (x >= 640 && x <= 782)
                    gui_engine_move(window);
                return 0;
            }
            if (gui_active_panel==GUI_PANEL_SETTINGS&&y>=118&&y<=151&&x>=730&&x<=820) {
                gui_apply_settings(window);
                return 0;
            }
            if(gui_active_panel==GUI_PANEL_STRENGTH&&y>=174&&y<=206&&x>=700&&x<=825) {
                gui_apply_settings(window);
                return 0;
            }
            if (gui_active_panel==GUI_PANEL_MATCH&&y>=62&&y<=96&&x>=700&&x<=825) {
                gui_run_tournament(window);
                return 0;
            }
            int file = (x - gui.board_x) / gui.square_size;
            int display_rank = (y - gui.board_y) / gui.square_size;
            if (x >= gui.board_x && y >= gui.board_y &&
                file >= 0 && file < 8 && display_rank >= 0 && display_rank < 8)
                gui_try_board_click(window, gui_display_square(file, display_rank));
            return 0;
        }
        case WM_TIMER:
            if (wparam == 2) {
                Color side = gui.position.side_to_move;
                if (!gui.unlimited_clock[side] && gui.clock_started && !gui.game_over &&
                    gui_clock_value(gui.position.side_to_move) <= 0.0)
                    gui_time_loss(gui.position.side_to_move);
                RECT client;GetClientRect(window,&client);
                RECT information={0,gui.board_y+gui.square_size*8,
                                  client.right,client.bottom};
                InvalidateRect(window,&information,FALSE);
            }
            return 0;
        case GUI_ENGINE_MOVE_MESSAGE:
            gui_engine_move(window);
            return 0;
        case GUI_ENGINE_RESULT_MESSAGE:
            gui_accept_engine_result(window,(GuiSearchJob *)lparam);
            return 0;
        case WM_SIZE:
            InvalidateRect(window, NULL, TRUE);
            return 0;
        case WM_DESTROY:
            atomic_store(&gui_window_closing,true);
            KillTimer(window, 2);
            if(!atomic_load(&gui_search_running))lazy_smp_pool_shutdown();
            gui_release_piece_images();
            if(gui_control_brush)DeleteObject(gui_control_brush);
            if(gui_ui_font)DeleteObject(gui_ui_font);
            if (gui_gdiplus_token) GdiplusShutdown(gui_gdiplus_token);
            PostQuitMessage(0);
            return 0;
        default:
            return DefWindowProcW(window, message, wparam, lparam);
    }
}

static int run_chess_gui(double base_seconds, double increment_seconds,
                         int max_depth) {
    INITCOMMONCONTROLSEX controls = {sizeof(controls), ICC_BAR_CLASSES};
    InitCommonControlsEx(&controls);
    HINSTANCE instance = GetModuleHandleW(NULL);
    WNDCLASSW window_class;
    memset(&window_class, 0, sizeof(window_class));
    window_class.lpfnWndProc = chess_window_proc;
    window_class.hInstance = instance;
    window_class.hCursor = LoadCursor(NULL, IDC_ARROW);
    window_class.hbrBackground = NULL;
    window_class.lpszClassName = GUI_CLASS_NAME;
    if (!RegisterClassW(&window_class) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
        return 1;

    memset(&gui, 0, sizeof(gui));
    gui.base_seconds[WHITE] = base_seconds;
    gui.base_seconds[BLACK] = base_seconds;
    gui.increment_seconds[WHITE] = increment_seconds;
    gui.increment_seconds[BLACK] = increment_seconds;
    gui.max_depth = max_depth;
    gui.threads = 1;
    gui.strength_elo[WHITE] = gui.strength_elo[BLACK] = 1500;
    gui.maximum_strength[WHITE] = gui.maximum_strength[BLACK] = false;
    gui_load_skill_overrides();
    search_thread_count = gui.threads;
    gui.lag_reserve_seconds = 0.01;
    gui.remaining[WHITE] = base_seconds;
    gui.remaining[BLACK] = base_seconds;
    gui.turn_started = timer_seconds();
    gui.clock_started = false;
    gui.unlimited_clock[WHITE] = false;
    gui.unlimited_clock[BLACK] = false;
    gui.selected_square = -1;
    gui.last_from_square = -1;
    gui.last_to_square = -1;
    snprintf(gui.engine_version, sizeof(gui.engine_version), "%s",
             ENGINE_VERSION);
    init_position(&gui.position);
    game_record_reset(&gui.game, &gui.position, false);
    gui.mode = GUI_HUMAN_VS_HUMAN;
    gui.human_side = WHITE;
    gui_refresh_status();
    snprintf(gui.opening, sizeof(gui.opening), "Not yet classified");
    gui_refresh_opening();

    GuiGdiplusStartupInput gdiplus_input = {1, NULL, FALSE, FALSE};
    if (GdiplusStartup(&gui_gdiplus_token, &gdiplus_input, NULL) == 0)
        gui_load_piece_images();

    HWND window = CreateWindowExW(
        0, GUI_CLASS_NAME, L"Chess Engine", WS_OVERLAPPEDWINDOW|WS_CLIPCHILDREN,
        CW_USEDEFAULT, CW_USEDEFAULT, 900, 1110,
        NULL, NULL, instance, NULL);
    if (!window) return 1;
    SetWindowTextA(window, ENGINE_BUILD_NAME);
    ShowWindow(window, SW_SHOW);
    UpdateWindow(window);

    MSG message;
    while (GetMessageW(&message, NULL, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return (int)message.wParam;
}
