"""脚本调用关系图（Script Dependency Graph）——防递归的纯逻辑部分。

这里处理的**不是**单个脚本内部的流程连线（那是执行器的事），而是
「脚本 A 调用了脚本 B」这一层关系。把这一层单独建成有向图之后：

  - 编辑时：准备加一条 A → B，先问「从 B 出发能不能走回 A」，能走回就拒绝；
  - 加载/运行前：整图做一次环检测 + 深度检查，有环就拒绝执行并报出完整调用链；
  - 运行时：执行器另有一份调用栈兜底（见 executor.py）。

**为什么要和前端各实现一份**：前端 src/lib/scriptGraph.ts 管「别让用户在画布上画出来」，
这里管「别人手改 JSON、旧版本文件、导入的脚本」也跑不起来。少任何一层都会留下
能跑成无限递归的洞——而无限递归的表现是程序卡死，用户根本无从下手。

调用图里的"脚本"有三种身份：
  - ROOT_NODE（"主脚本"）：这份 .agflow 最外层的流程。它不可被调用（没有边指向它）
  - 子脚本 id：稳定标识。**绝不能用名字当 key**：改名不该断开调用关系
  - 不存在的 id：不算图中的边，单独作为"脚本不存在"报错（它不该被误判成环）

纯函数、无副作用、不依赖引擎其它模块（可以脱离 Windows 单独跑断言）。
"""
from __future__ import annotations

# 调用图里代表「根脚本」的虚拟节点
ROOT_NODE = "__root__"

# 允许的最大嵌套层数（运行时第二道防线，executor 用）。
#
# 16 是"远超正常需求、又不会把递归栈撑爆"的取值：真实脚本嵌套到 3~4 层已经很夸张，
# 而每层只是 Python 的普通函数递归，16 层完全安全。
# 环检测是更根本的防线，这个上限只用来兜住"环检测漏掉的、或运行时才出现的"极端情况。
MAX_SCRIPT_DEPTH = 16


def collect_calls(flow) -> list[str]:
    """一段流程里被调用的脚本 id（按出现顺序、去重）。"""
    out: list[str] = []
    if not isinstance(flow, dict):
        return out
    for n in flow.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        # 两种形状都认：引擎负载是扁平的 {type, params}，
        # 文件/画布是嵌套的 {data: {stepType, params}}
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        ntype = data.get("stepType") or n.get("type")
        if ntype != "script_call":
            continue
        params = (data.get("params") if data else None) or n.get("params") or {}
        sid = str(params.get("script_id") or "").strip()
        if sid and sid not in out:
            out.append(sid)
    return out


def normalize_scripts(raw) -> dict[str, dict]:
    """脚本注册表：id → 子脚本（缺 id 的条目会被忽略）。"""
    out: dict[str, dict] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        sid = str(value.get("id") or key or "").strip()
        if not sid:
            continue
        nodes = value.get("nodes")
        edges = value.get("edges")
        out[sid] = {
            "id": sid,
            "name": str(value.get("name") or sid),
            "nodes": nodes if isinstance(nodes, list) else [],
            "edges": edges if isinstance(edges, list) else [],
        }
    return out


def build_graph(root_flow, scripts, include_root: bool = True) -> dict[str, list[str]]:
    """建图：key = 脚本 id（根用 ROOT_NODE），value = 它直接调用的脚本 id。

    只有出现在注册表里的目标才会成为边 —— 指向不存在的脚本不算依赖，
    否则"删了一个子脚本"会被误报成环，用户看到的是完全无关的错误。
    """
    reg = normalize_scripts(scripts)
    graph: dict[str, list[str]] = {}
    if include_root:
        graph[ROOT_NODE] = []
    for sid in reg:
        graph[sid] = []

    def link(src: str, flow) -> None:
        for dst in collect_calls(flow):
            if dst in graph and dst not in graph[src]:
                graph[src].append(dst)

    if include_root:
        link(ROOT_NODE, root_flow)
    for sid, sub in reg.items():
        link(sid, sub)
    return graph


def find_path(graph: dict[str, list[str]], src: str, dst: str) -> list[str] | None:
    """从 src 出发能否走到 dst；能则返回路径 [src, …, dst]，不能返回 None（BFS，最短路）。"""
    if src == dst:
        return [src]
    prev: dict[str, str] = {}
    seen = {src}
    queue = [src]
    while queue:
        cur = queue.pop(0)
        for nxt in graph.get(cur, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            prev[nxt] = cur
            if nxt == dst:
                path = [dst]
                p = cur
                while p != src:
                    path.insert(0, p)
                    p = prev[p]
                path.insert(0, src)
                return path
            queue.append(nxt)
    return None


def would_create_cycle(graph: dict[str, list[str]], src: str, dst: str) -> list[str] | None:
    """准备加一条 src → dst，判断会不会成环。

    成环的充要条件是「从 dst 出发已经能回到 src」。返回值是**闭合后的完整环路径**。

    注意不能只判断 src != dst：那只覆盖"自己调自己"，
    A → B → C → A 这种间接环必须靠可达性判定。
    """
    if not src or not dst:
        return None
    if src == dst:
        return [src, dst]
    back = find_path(graph, dst, src)
    return [src, *back] if back else None


def find_any_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """整图找一条环（找不到返回 None）。运行前的整体校验用它。

    用白/灰/黑三色 DFS：命中灰色节点说明它还在当前递归栈里，
    栈里从它到栈顶那一段就是环（返回值末尾会重复一次起点，便于直接读成 "A → B → A"）。
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in graph}

    def dfs(node: str, stack: list[str]) -> list[str] | None:
        color[node] = GRAY
        stack.append(node)
        for nxt in graph.get(node, []):
            c = color.get(nxt, WHITE)
            if c == GRAY:
                at = stack.index(nxt)
                return [*stack[at:], nxt]
            if c == WHITE:
                found = dfs(nxt, stack)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for k in list(graph.keys()):
        if color.get(k, WHITE) == WHITE:
            found = dfs(k, [])
            if found:
                return found
    return None


def longest_chain(graph: dict[str, list[str]], start: str = ROOT_NODE) -> list[str]:
    """从 start 出发的最长调用链（无环时才有意义）。

    用记忆化 DFS：DAG 上每个节点的"从这里往下的最长链"只算一次。
    """
    memo: dict[str, list[str]] = {}

    def walk(node: str, seen: set[str]) -> list[str]:
        if node in memo:
            return memo[node]
        best: list[str] = [node]
        for nxt in graph.get(node, []):
            if nxt in seen:  # 有环时兜底，正常流程里走不到
                continue
            cand = [node, *walk(nxt, seen | {nxt})]
            if len(cand) > len(best):
                best = cand
        memo[node] = best
        return best

    return walk(start, {start})


def name_map(scripts) -> dict[str, str]:
    """id → 名字（显示用；找不到的 id 由调用方退回 id 本身）。"""
    out: dict[str, str] = {}
    for sid, sub in normalize_scripts(scripts).items():
        out[sid] = sub["name"]
    return out


def chain_text(ids: list[str], names: dict[str, str] | None = None) -> str:
    """把一串脚本 id 写成「A → B → C」，便于直接塞进提示语。"""
    names = names or {}
    parts = []
    for sid in ids:
        if sid == ROOT_NODE:
            parts.append("主脚本")
        else:
            parts.append(names.get(sid) or sid)
    return " → ".join(parts)


def validate_scripts(flow) -> list[str]:
    """运行/加载前的整体校验，返回**中文错误列表**（空列表 = 通过）。

    检查三项，顺序按"用户最容易理解"排：
      1. 调用了不存在的脚本 —— 说清是哪个脚本里的哪个调用点
      2. 存在循环调用       —— 说清完整调用链
      3. 嵌套层数超上限     —— 说清最深的那条链

    第 1 项必须**在环检测之前**单独处理：缺失的脚本不是图中的边，
    如果把它当成边，一个"删掉的子脚本"会被报成环，用户完全看不懂。
    """
    errors: list[str] = []
    if not isinstance(flow, dict):
        return ["流程必须是 JSON 对象"]

    reg = normalize_scripts(flow.get("scripts"))
    names = name_map(reg)

    def label(sid: str) -> str:
        return "主脚本" if sid == ROOT_NODE else (names.get(sid) or sid)

    # ---- 1. 脚本不存在 ----
    missing: list[str] = []
    for sid in collect_calls(flow):
        if sid not in reg:
            missing.append(f"主脚本里的「调用脚本」步骤指向了一个不存在的脚本（{sid}）")
    for owner_id, sub in reg.items():
        for sid in collect_calls(sub):
            if sid not in reg:
                missing.append(
                    f"脚本「{sub['name']}」里的「调用脚本」步骤指向了一个不存在的脚本（{sid}）"
                )
    if missing:
        errors.append(
            "有子脚本找不到（可能是删除了、或从别处导入时缺失）：\n  "
            + "\n  ".join(missing)
            + "\n请在编辑器里重新选择这些步骤要调用的脚本，或把缺失的子脚本导入回来。"
        )

    # ---- 2. 循环调用 ----
    graph = build_graph(flow, reg, include_root=True)
    cycle = find_any_cycle(graph)
    if cycle:
        errors.append(
            "存在循环调用，无法运行：\n  "
            + chain_text(cycle, names)
            + "\n（脚本之间不允许互相调用成环，否则会无限嵌套下去。请打断其中一条调用）"
        )

    # ---- 3. 嵌套过深 ----
    if not cycle:
        chain = longest_chain(graph, ROOT_NODE)
        # chain 含 ROOT_NODE 本身，实际嵌套层数 = len(chain) - 1
        depth = len(chain) - 1
        if depth > MAX_SCRIPT_DEPTH:
            errors.append(
                f"脚本嵌套层数过深（{depth} 层，上限 {MAX_SCRIPT_DEPTH} 层）：\n  "
                + chain_text(chain, names)
                + "\n请把其中几层合并成一层。"
            )

    return errors
