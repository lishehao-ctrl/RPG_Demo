from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable

from rpg_backend.author_v2.contracts import PropagationPriorityPolicy, ShellPropagationGraphPolicy
from rpg_backend.play_v2.contracts import LatentEventKind, ShellPropagationEdgeRecord


@dataclass(frozen=True)
class _ShellEdge:
    edge_id: str
    from_node: str
    to_node: str
    anchor_token: str
    signal_family: str
    note: str


_GRAPH: dict[str, tuple[_ShellEdge, ...]] = {
    "campus_romance": (
        _ShellEdge("campus_stage_to_audience", "舞台", "台下", "台下", "peer_spread", "舞台风波先落到台下眼神。"),
        _ShellEdge("campus_audience_to_judges", "台下", "评审席", "评审", "institutional_shift", "台下情绪会把评审温度带偏。"),
        _ShellEdge("campus_judges_to_slots", "评审席", "名额池", "名额", "institutional_shift", "评审态度会直接改名额预期。"),
        _ShellEdge("campus_club_to_peers", "社团核心", "熟人圈", "社团", "peer_spread", "社团核心会把口风扩散到熟人圈。"),
        _ShellEdge("campus_peers_to_alignment", "熟人圈", "站队层", "站队", "peer_spread", "熟人传播最终落成公开站队。"),
    ),
    "entertainment_scandal": (
        _ShellEdge("ent_set_to_camera", "现场", "镜头", "镜头", "public_wave", "现场动作先被镜头定义。"),
        _ShellEdge("ent_camera_to_screen", "镜头", "公屏", "公屏", "public_wave", "镜头叙事会在公屏被放大。"),
        _ShellEdge("ent_screen_to_hotsearch", "公屏", "热搜", "热搜", "public_wave", "公屏节奏会被热搜接管。"),
        _ShellEdge("ent_hotsearch_to_pr", "热搜", "公关线", "公关", "institutional_shift", "热搜变化会迫使公关线切口。"),
        _ShellEdge("ent_pr_to_cutoff", "公关线", "切割链", "切割", "institutional_shift", "公关动作会转为切割执行。"),
    ),
    "office_power": (
        _ShellEdge("office_room_to_line", "会议桌", "汇报线", "会议室", "institutional_shift", "会议桌风向会改汇报线口径。"),
        _ShellEdge("office_line_to_review", "汇报线", "考核面", "考核", "institutional_shift", "汇报线会在考核里沉淀后果。"),
        _ShellEdge("office_review_to_rank", "考核面", "职级线", "职级", "institutional_shift", "考核温度会改职级预期。"),
    ),
    "wealth_families": (
        _ShellEdge("wealth_table_to_family", "主桌", "家族口风", "家宴", "relationship_pressure", "主桌波动会先改家宴口风。"),
        _ShellEdge("wealth_family_to_order", "家族口风", "顺位线", "顺位", "relationship_pressure", "家族口风最终落到顺位判断。"),
        _ShellEdge("wealth_order_to_board", "顺位线", "董事会", "董事会", "institutional_shift", "顺位变动会传导到董事会动作。"),
    ),
}


_KIND_EDGE_HINT: dict[LatentEventKind, tuple[str, ...]] = {
    "relationship_debt": ("alignment", "order", "peers"),
    "public_wave": ("camera", "screen", "audience", "public"),
    "secret_pressure": ("review", "hotsearch", "judges", "board"),
    "npc_action": ("cutoff", "alignment", "line", "family"),
}


def _policy_edges(shell_id: str, graph_policy: ShellPropagationGraphPolicy | None) -> tuple[_ShellEdge, ...] | None:
    if graph_policy is None:
        return None
    if graph_policy.shell_id != shell_id:
        return None
    rows = tuple(
        _ShellEdge(
            edge_id=edge.edge_id,
            from_node=edge.from_node,
            to_node=edge.to_node,
            anchor_token=edge.anchor_token,
            signal_family=edge.signal_family,
            note=edge.note,
        )
        for edge in graph_policy.edges
    )
    return rows or None


def _stable_index(key: str, size: int) -> int:
    if size <= 1:
        return 0
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def pick_shell_edge(
    *,
    shell_id: str,
    latent_kind: LatentEventKind | None,
    turn_index: int,
    segment_role: str,
    graph_policy: ShellPropagationGraphPolicy | None = None,
    priority_policy: PropagationPriorityPolicy | None = None,
) -> ShellPropagationEdgeRecord | None:
    edges = _policy_edges(shell_id, graph_policy) or _GRAPH.get(shell_id)
    if not edges:
        return None
    selected: Iterable[_ShellEdge] = edges
    if latent_kind is not None:
        hints = _KIND_EDGE_HINT.get(latent_kind, ())
        hinted = [edge for edge in edges if any(token in edge.edge_id for token in hints)]
        if hinted:
            selected = hinted
    if graph_policy is not None and segment_role in {"reveal", "terminal"}:
        preferred = set(graph_policy.key_segment_preferred_edges)
        if preferred:
            prioritized = [edge for edge in selected if edge.edge_id in preferred]
            if prioritized:
                selected = prioritized
    if priority_policy is not None and priority_policy.shell_id == shell_id:
        preferred_by_role = list(priority_policy.edge_priority_by_segment_role.get(segment_role, []))
        if preferred_by_role:
            preferred_ids = set(preferred_by_role)
            prioritized = [edge for edge in selected if edge.edge_id in preferred_ids]
            if prioritized:
                selected = prioritized
    selected_list = list(selected)
    idx = _stable_index(f"{shell_id}|{latent_kind}|{turn_index}|{segment_role}", len(selected_list))
    chosen = selected_list[idx]
    return ShellPropagationEdgeRecord(
        edge_id=chosen.edge_id,
        shell_id=shell_id,
        from_node=chosen.from_node,
        to_node=chosen.to_node,
        anchor_token=chosen.anchor_token,
        signal_family=chosen.signal_family,
        note=chosen.note,
    )


def edge_signal_clause(*, edge: ShellPropagationEdgeRecord, role: str) -> str:
    if role == "counter":
        return f"{edge.from_node}这边已经把口风带向{edge.to_node}，{edge.anchor_token}正在定义后面的解释权。"
    return f"{edge.from_node}到{edge.to_node}这条传播链已经跑起来了，{edge.anchor_token}那边会继续放大后果。"


def get_shell_edge(shell_id: str, edge_id: str, *, graph_policy: ShellPropagationGraphPolicy | None = None) -> ShellPropagationEdgeRecord | None:
    edges = _policy_edges(shell_id, graph_policy) or _GRAPH.get(shell_id, ())
    chosen = next((item for item in edges if item.edge_id == edge_id), None)
    if chosen is None:
        return None
    return ShellPropagationEdgeRecord(
        edge_id=chosen.edge_id,
        shell_id=shell_id,
        from_node=chosen.from_node,
        to_node=chosen.to_node,
        anchor_token=chosen.anchor_token,
        signal_family=chosen.signal_family,
        note=chosen.note,
    )
