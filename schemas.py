from pydantic import BaseModel

# ---- Sessions ----
class SessionCreate(BaseModel):
    site: str = "betsolid"
    session_code: str
    nickname: str | None = None
    game_type: str | None = None
    currency: str = "EUR"
    sb: float | None = None
    bb: float | None = None
    table_name: str | None = None
    start_date: str | None = None
    duration: str | None = None
    game_count: int | None = None


class SessionOut(BaseModel):
    id: int
    site: str
    session_code: str

    class Config:
        from_attributes = True


class SessionDetailOut(BaseModel):
    id: int
    site: str
    session_code: str
    nickname: str | None = None
    game_type: str | None = None
    currency: str | None = None
    sb: float | None = None
    bb: float | None = None
    table_name: str | None = None
    start_date: str | None = None
    duration: str | None = None
    game_count: int | None = None

    class Config:
        from_attributes = True


class SessionListOut(BaseModel):
    id: int
    site: str
    session_code: str
    nickname: str | None = None
    game_type: str | None = None
    sb: float | None = None
    bb: float | None = None
    start_date: str | None = None

    class Config:
        from_attributes = True



# ---- Hands ----
class HandCreate(BaseModel):
    session_id: int
    site_hand_id: str
    started_at: str | None = None
    max_players: int | None = None
    button_seat: int | None = None
    variant: str | None = "NLHE"
    currency: str | None = "EUR"
    sb: float | None = None
    bb: float | None = None


class HandListOut(BaseModel):
    id: int
    site_hand_id: str
    session_id: int
    started_at: str | None = None

    class Config:
        from_attributes = True


class HandOut(BaseModel):
    id: int
    site_hand_id: str
    session_id: int
    started_at: str | None = None
    max_players: int | None = None
    button_seat: int | None = None
    variant: str | None = None
    currency: str | None = None
    sb: float | None = None
    bb: float | None = None

    class Config:
        from_attributes = True


# ---- Player stats ----
class PlayerStatsOut(BaseModel):
    player_name: str
    hands: int
    bet_total: float
    win_total: float
    net: float

# ---- Hand Players ----
class HandPlayerCreate(BaseModel):
    hand_id: int
    player_name: str
    seat: int | None = None
    is_dealer: bool | None = None
    stack_start: float | None = None
    bet_total: float | None = 0.0
    win_total: float | None = 0.0
    rake: float | None = 0.0
    cashout: bool | None = None
    cashout_fee: float | None = 0.0


class HandPlayerOut(BaseModel):
    id: int
    hand_id: int
    player_name: str
    seat: int | None = None
    is_dealer: bool | None = None
    stack_start: float | None = None
    bet_total: float | None = None
    win_total: float | None = None
    rake: float | None = None
    cashout: bool | None = None
    cashout_fee: float | None = None

    class Config:
        from_attributes = True

# ---- Actions ----
class ActionCreate(BaseModel):
    hand_id: int
    street: int              # 1=preflop, 2=flop, 3=turn, 4=river (eller 0-4 hvis du vil)
    seq: int                 # rekkefølge i street (1,2,3...)
    player_name: str
    action: str              # "fold", "call", "raise", "bet", "check", "sb", "bb"
    amount: float = 0.0
    action_type_code: int | None = None  # valgfritt (til XML mapping senere)


class ActionOut(BaseModel):
    id: int
    hand_id: int
    street: int
    seq: int
    player_name: str
    action: str
    amount: float
    action_type_code: int | None = None

    class Config:
        from_attributes = True

# ---- HUD Stats ----

class PlayerHudOut(BaseModel):
    player_name: str
    hands_played: int

    vpip_hands: int
    vpip_pct: float

    pfr_hands: int
    pfr_pct: float

    threebet_hands: int
    threebet_pct: float

    cb_flop_opp: int
    cb_flop_made: int
    cb_flop_pct: float

    fold_to_cb_flop_opp: int
    fold_to_cb_flop: int
    fold_to_cb_flop_pct: float

    fold_to_3bet_opp: int
    fold_to_3bet: int
    fold_to_3bet_pct: float

    player_type: str = "UNKNOWN"
    confidence: str = "low"
    confidence_overall: str = "low"
    confidence_vpip_pfr: str = "low"
    confidence_3bet: str = "low"
    confidence_cbet_flop: str = "low"
    confidence_fold_to_cbet: str = "low"
    confidence_fold_to_3bet: str = "low"

class SessionHudOut(BaseModel):
    session_id: int
    players: list[PlayerHudOut]

class LeakOut(BaseModel):
    leak_id: str
    severity: str
    message: str
    suggestion: str
    stat: str
    value: float | int
    opp: int | None = None
    confidence: str | None = None
    examples: list[str] | None = None
    rules: list[str] | None = None



class PlayerLeaksOut(BaseModel):
    player_name: str
    leaks: list[LeakOut]

class SessionPlayerLeaksOut(BaseModel):
    player_name: str
    hands_played: int
    leaks: list[LeakOut]
    leak_score: int



class SessionLeaksOut(BaseModel):
    session_id: int
    min_hands: int
    players: list[SessionPlayerLeaksOut]

class PlayerInsightsOut(BaseModel):
    player_name: str
    leaks: list[LeakOut]
    observations: list[LeakOut]


class SessionInsightsPlayerOut(BaseModel):
    player_name: str
    hands_played: int
    leak_score: int
    obs_score: int
    leaks: list[LeakOut]
    observations: list[LeakOut]


class SessionInsightsOut(BaseModel):
    session_id: int
    min_hands: int
    mode: str
    players: list[SessionInsightsPlayerOut]

class PosStatsOut(BaseModel):
    hands: int
    vpip_hands: int
    vpip_pct: float
    pfr_hands: int
    pfr_pct: float


class PlayerHudByPosOut(BaseModel):
    player_name: str
    session_id: int | None = None
    by_pos: dict[str, PosStatsOut]


class PosFold3betOut(BaseModel):
    opp: int
    fold: int
    fold_pct: float

class PlayerFoldTo3betByPosOut(BaseModel):
    player_name: str
    session_id: int | None = None
    by_pos: dict[str, PosFold3betOut]

class PosFoldCbetOut(BaseModel):
    opp: int
    fold: int
    fold_pct: float


class PlayerFoldToCbetByPosOut(BaseModel):
    player_name: str
    session_id: int | None = None
    by_pos: dict[str, PosFoldCbetOut]


class PosCbetOut(BaseModel):
    opp: int
    made: int
    pct: float

class PlayerCbetFlopByPosOut(BaseModel):
    player_name: str
    session_id: int | None = None
    by_pos: dict[str, PosCbetOut]

class PlayerCbetFlopByPosSplitOut(BaseModel):
    player_name: str
    session_id: int | None = None
    hu: dict[str, PosCbetOut]
    mw: dict[str, PosCbetOut]

class PreflopEdgePosOut(BaseModel):
    hands: int
    vpip_pct: float
    pfr_pct: float
    gap: float
    verdict: str
    advice: list[str]

class PlayerPreflopEdgesOut(BaseModel):
    player_name: str
    session_id: int | None = None
    by_pos: dict[str, PreflopEdgePosOut]


class LeakImpactOut(BaseModel):
    leak_id: str
    hands: int
    net_total: float
    net_per_hand: float
    share_of_total_pct: float
    note: str


class PlayerLeakImpactOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    impacts: list[LeakImpactOut]

class PlanItemOut(BaseModel):
    title: str
    priority: int
    impact_share_pct: float
    rationale: str
    actions: list[str]


class PlayerImpactPlanOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    top_impacts: list[LeakImpactOut]
    plan: list[PlanItemOut]

class ImpactDeltaOut(BaseModel):
    leak_id: str
    from_net: float
    to_net: float
    delta_net: float
    from_share: float
    to_share: float
    delta_share: float
    from_hands: int
    to_hands: int


class CompareKeyMetricsOut(BaseModel):
    utg_vpip_pct_from: float | None = None
    utg_vpip_pct_to: float | None = None
    utg_pfr_pct_from: float | None = None
    utg_pfr_pct_to: float | None = None

    mp_vpip_pct_from: float | None = None
    mp_vpip_pct_to: float | None = None
    mp_pfr_pct_from: float | None = None
    mp_pfr_pct_to: float | None = None

    fold_to_3bet_pct_from: float | None = None
    fold_to_3bet_pct_to: float | None = None


class SessionCompareOut(BaseModel):
    player_name: str
    from_session_id: int
    to_session_id: int
    from_net_total: float
    to_net_total: float
    delta_net_total: float
    impacts: list[ImpactDeltaOut]
    key_metrics: CompareKeyMetricsOut
    verdict: str
    next_focus: str


class SpotCostOut(BaseModel):
    spot_id: str
    hands: int
    net_total: float
    net_per_hand: float
    share_of_total_pct: float
    note: str
    example_hand_ids: list[int] | None = None
    example_details: list[str] | None = None




class PlayerSpotCostsOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    spots: list[SpotCostOut]


class SpotPlanItemOut(BaseModel):
    spot_id: str
    priority: int
    share_of_total_pct: float
    rationale: str
    actions: list[str]


class PlayerBBSpotPlanOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    top_spots: list[SpotCostOut]
    plan: list[SpotPlanItemOut]


class Fold3BetBucketOut(BaseModel):
    bucket: str
    hands: int
    net_total: float
    net_per_hand: float
    share_of_total_pct: float
    example_hand_ids: list[int] | None = None
    note: str


class PlayerFold3BetCostBySizeOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    buckets: list[Fold3BetBucketOut]


class ThreeBetPlanItemOut(BaseModel):
    bucket: str
    priority: int
    hands: int
    net_total: float
    share_of_total_pct: float
    rationale: str
    actions: list[str]
    example_hand_ids: list[int] | None = None


class PlayerThreeBetPlanOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    buckets: list[Fold3BetBucketOut]
    plan: list[ThreeBetPlanItemOut]

class Fold3BetBucketSplitOut(BaseModel):
    bucket: str              # vs_small_3bet / vs_medium_3bet / vs_big_3bet
    stance: str              # "IP" eller "OOP"
    hands: int
    net_total: float
    net_per_hand: float
    share_of_total_pct: float
    example_hand_ids: list[int] | None = None
    note: str


class PlayerFold3BetCostBySizeSplitOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    buckets: list[Fold3BetBucketSplitOut]


class ThreeBetPlanSplitItemOut(BaseModel):
    bucket: str
    stance: str
    priority: int
    hands: int
    net_total: float
    share_of_total_pct: float
    rationale: str
    actions: list[str]
    example_hand_ids: list[int] | None = None


class PlayerThreeBetPlanSplitOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    buckets: list[Fold3BetBucketSplitOut]
    plan: list[ThreeBetPlanSplitItemOut]


class Fold3BetBucketOpenPosOut(BaseModel):
    bucket: str          # vs_small_3bet / vs_medium_3bet / vs_big_3bet
    stance: str          # IP / OOP
    open_pos: str        # UTG/MP/CO/BTN/SB/BB
    hands: int
    net_total: float
    net_per_hand: float
    share_of_total_pct: float
    example_hand_ids: list[int] | None = None
    note: str


class PlayerFold3BetCostBySizeSplitByOpenPosOut(BaseModel):
    player_name: str
    session_id: int | None = None
    session_net_total: float
    buckets: list[Fold3BetBucketOpenPosOut]

class ThreeBetResponseCellOut(BaseModel):
    open_group: str          # EARLY / LATE / BLINDS (eller UTG/MP/CO/BTN hvis group_openpos=false)
    stance: str              # IP / OOP
    bucket: str              # vs_small_3bet / vs_medium_3bet / vs_big_3bet
    faced: int
    fold: int
    call: int
    fourbet: int
    fold_pct: float
    call_pct: float
    fourbet_pct: float
    example_hand_ids: list[int] | None = None
    note: str | None = None
    confidence: str = "low"



class PlayerThreeBetResponseMatrixOut(BaseModel):
    player_name: str
    session_id: int | None = None
    min_faced: int
    group_openpos: bool
    total_faced: int = 0                 
    cells_returned: int = 0              
    recommended_min_faced: int = 1       
    cells: list[ThreeBetResponseCellOut]



class PlayerThreeBetResponseMatrixOut(BaseModel):
    player_name: str
    session_id: int | None = None
    min_faced: int
    group_openpos: bool
    total_faced: int
    cells_returned: int
    recommended_min_faced: int
    cells: list[ThreeBetResponseCellOut]


class ThreeBetSampleTargetOut(BaseModel):
    open_group: str
    stance: str
    bucket: str
    priority: int
    faced: int
    need_more_for_medium: int
    why: str
    micro_rule: str
    example_hand_ids: list[int] | None = None


class PlayerThreeBetSamplingPlanOut(BaseModel):
    player_name: str
    session_id: int | None = None
    total_faced: int
    targets: list[ThreeBetSampleTargetOut]


# ---- Hole card results ----
class HoleCardResultOut(BaseModel):
    card1: str
    card2: str
    hands: int
    won: int
    tied: int
    lost: int
    net_total: float
    avg_net: float
    bb_per_100: float | None = None


class PlayerHoleCardsOut(BaseModel):
    player_name: str
    session_id: int | None = None
    total_hands: int
    combos: list[HoleCardResultOut]


class ThreeBetSampleTargetOut(BaseModel):
    open_group: str
    stance: str
    bucket: str
    priority: int
    faced: int
    need_more_for_medium: int
    why: str
    micro_rule: str
    example_hand_ids: list[int] | None = None


class PlayerThreeBetSamplingPlanOut(BaseModel):
    player_name: str
    session_id: int | None = None
    total_faced: int
    targets: list[ThreeBetSampleTargetOut]

class NextRuleOut(BaseModel):
    rule: str
    why: str
    target: str  # f.eks "LATE/IP/vs_medium_3bet"
    need_more_for_medium: int


class PlayerNextSessionRules3BetOut(BaseModel):
    player_name: str
    session_id: int | None = None
    total_faced: int
    goal: str
    rules: list[NextRuleOut]

class NextRuleOut(BaseModel):
    rule: str
    why: str
    target: str
    need_more_for_medium: int
    example_hand_ids: list[int] | None = None   # <-- NY

class LiveHint3BetRequest(BaseModel):
    player_name: str
    villain_name: str | None = None
    session_id: int | None = None
    open_group: str          # EARLY/LATE/BLINDS
    stance: str              # IP/OOP
    bucket: str              # vs_small_3bet/vs_medium_3bet/vs_big_3bet


class LiveHint3BetResponse(BaseModel):
    situation: str
    player_name: str
    villain_name: str | None = None
    session_id: int | None = None
    confidence: str
    hint: str
    watchouts: list[str]
    evidence_hand_ids: list[int] | None = None
    one_liner: str


class LiveHint3BetAutoResponse(BaseModel):
    found: bool
    reason: str | None = None

    player_name: str
    session_id: int | None = None

    hand_id: int | None = None
    villain_name: str | None = None

    open_group: str | None = None
    stance: str | None = None
    bucket: str | None = None

    confidence: str | None = None
    hint: str | None = None
    watchouts: list[str] | None = None
    evidence_hand_ids: list[int] | None = None

class PlayerResultsOut(BaseModel):
    hands: int
    net_total: float
    bb_per_100: float
    confidence: str


class PlayerProfileOut(BaseModel):
    player_name: str
    session_id: int | None = None

    player_type: str
    confidence: str

    aggression_score: int
    aggression_label: str

    fundamentals_score: int
    fundamentals_label: str

    results: PlayerResultsOut

    strength_score: int
    strength_label: str

    notes: list[str] = []

class SessionPlayerStatsOut(BaseModel):
    player_name: str
    hands: int
    bet_total: float
    win_total: float
    net_total: float
    bb_per_hand: float

class SessionStatsOut(BaseModel):
    session_id: int
    session_code: str
    total_players: int
    total_hands: int
    players: list[SessionPlayerStatsOut]
