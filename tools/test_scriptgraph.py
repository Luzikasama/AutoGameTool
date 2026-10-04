"""scriptgraph.py 的断言测试（防递归的纯逻辑部分）。

跑法：
    python tools/test_scriptgraph.py

为什么值得单独测：环检测的失败方式非常"安静"——
少判一种情况不会报错，只会在用户挂机时把程序卡死。
而这些判定本身只有几十行，用表格驱动把边界情况钉死最划算。

覆盖的就是设计文档里那张验收表：
  A→B               允许
  A→A               拒绝（自己调自己）
  A→B→A             拒绝
  A→B→C→A           拒绝
  A→B→C→B           拒绝（环不在根上）
  A→B, A→C, B→D, C→D 允许（菱形不是环）
  调用不存在的脚本    报"脚本不存在"，**不能**报成"循环调用"
  嵌套超上限         拒绝并给出最深链
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

import scriptgraph as sg  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
        return
    FAILED.append(name)
    print(f"  FAIL {name} {extra}")


def call_node(nid: str, script_id: str) -> dict:
    """一个「调用脚本」节点（引擎负载的扁平形状）。"""
    return {"id": nid, "type": "script_call", "params": {"script_id": script_id, "name": script_id}}


def delay_node(nid: str) -> dict:
    return {"id": nid, "type": "delay", "params": {"ms": 100}}


def flow(nodes=None, edges=None, scripts=None) -> dict:
    return {
        "nodes": nodes or [delay_node("n1")],
        "edges": edges or [],
        "scripts": {s["id"]: s for s in (scripts or [])},
    }


def sub(sid: str, nodes=None, edges=None) -> dict:
    return {"id": sid, "name": f"脚本{sid}", "nodes": nodes or [], "edges": edges or []}


def main() -> int:
    print("[1] collect_calls / normalize_scripts")
    f = flow(nodes=[call_node("n1", "A"), call_node("n2", "B"), call_node("n3", "A"), delay_node("n4")])
    check("去重且保持顺序", sg.collect_calls(f) == ["A", "B"], str(sg.collect_calls(f)))
    check("嵌套形状（data.stepType）也认", sg.collect_calls(
        {"nodes": [{"id": "x", "data": {"stepType": "script_call", "params": {"script_id": "Z"}}}]}
    ) == ["Z"])
    check("空 id 被忽略", sg.collect_calls({"nodes": [call_node("n", "")]}) == [])
    check("normalize 丢弃非对象条目", sg.normalize_scripts({"a": 1, "b": {"id": "b"}}) == {
        "b": {"id": "b", "name": "b", "nodes": [], "edges": []}})
    check("normalize 容忍 None", sg.normalize_scripts(None) == {})

    print("[2] A 调 B（无环）→ 允许")
    f = flow(nodes=[call_node("n1", "A")], scripts=[sub("A"), sub("B")])
    g = sg.build_graph(f, f["scripts"])
    check("图中无边 A→B（A 没调 B）", sg.find_any_cycle(g) is None)
    check("根 → A", sg.find_path(g, sg.ROOT_NODE, "A") == [sg.ROOT_NODE, "A"])
    check("A 走不到根", sg.find_path(g, "A", sg.ROOT_NODE) is None)

    print("[3] 自己调自己 A→A → 拒绝")
    g = sg.build_graph(flow(nodes=[call_node("n1", "A")], scripts=[sub("A", [call_node("a1", "A")])]),
                       {"A": sub("A", [call_node("a1", "A")])})
    cyc = sg.find_any_cycle(g)
    check("找到自环", cyc is not None and cyc[0] == cyc[-1], str(cyc))
    check("链文本含 A → A", sg.chain_text([sg.ROOT_NODE, "A", "A"], {"A": "脚本A"}) == "主脚本 → 脚本A → 脚本A")

    print("[4] A→B→A → 拒绝")
    nodes = [call_node("n1", "A")]
    scripts = {"A": sub("A", [call_node("a1", "B")]), "B": sub("B", [call_node("b1", "A")])}
    g = sg.build_graph(flow(nodes=nodes), scripts)
    cyc = sg.find_any_cycle(g)
    check("找到环", cyc is not None, str(cyc))
    check("环是闭合的（首尾同一个）", cyc is not None and cyc[0] == cyc[-1])
    check("环的长度为 3（A→B→A）", cyc is not None and len(cyc) == 3, str(cyc))

    print("[5] A→B→C→A → 拒绝")
    scripts = {
        "A": sub("A", [call_node("a1", "B")]),
        "B": sub("B", [call_node("b1", "C")]),
        "C": sub("C", [call_node("c1", "A")]),
    }
    g = sg.build_graph(flow(nodes=[call_node("n1", "A")]), scripts)
    cyc = sg.find_any_cycle(g)
    check("找到 3 步环", cyc is not None and len(cyc) == 4, str(cyc))
    errs = sg.validate_scripts(flow(nodes=[call_node("n1", "A")], scripts=list(scripts.values())))
    check("validate 报出循环调用", any("循环调用" in e for e in errs), str(errs))
    check("报错里带完整链", any("脚本A → 脚本B → 脚本C → 脚本A" in e for e in errs), str(errs))

    print("[6] A→B→C→B → 拒绝（环不在根上）")
    scripts = {
        "A": sub("A", [call_node("a1", "B")]),
        "B": sub("B", [call_node("b1", "C")]),
        "C": sub("C", [call_node("c1", "B")]),
    }
    g = sg.build_graph(flow(nodes=[call_node("n1", "A")]), scripts)
    check("找到环", sg.find_any_cycle(g) is not None)

    print("[7] 菱形 A→B, A→C, B→D, C→D → 允许")
    scripts = {
        "A": sub("A", [call_node("a1", "B"), call_node("a2", "C")]),
        "B": sub("B", [call_node("b1", "D")]),
        "C": sub("C", [call_node("c1", "D")]),
        "D": sub("D", [delay_node("d1")]),
    }
    f = flow(nodes=[call_node("n1", "A")], scripts=list(scripts.values()))
    g = sg.build_graph(f, f["scripts"])
    check("菱形不算环", sg.find_any_cycle(g) is None)
    check("validate 通过", sg.validate_scripts(f) == [], str(sg.validate_scripts(f)))
    check("重复调用同一脚本只算一条边", g["A"] == ["B", "C"], str(g.get("A")))

    print("[8] 调用不存在的脚本 → 报'脚本不存在'，不能报成环")
    f = flow(nodes=[call_node("n1", "GHOST")], scripts=[sub("A")])
    errs = sg.validate_scripts(f)
    check("报出不存在的脚本", any("不存在" in e or "找不到" in e for e in errs), str(errs))
    check("不说'循环调用'", not any("循环调用" in e for e in errs), str(errs))
    check("指向不存在的脚本不成为边", sg.build_graph(f, f["scripts"])[sg.ROOT_NODE] == [])

    print("[9] 嵌套层数上限")
    k = sg.MAX_SCRIPT_DEPTH + 2
    scripts = []
    for i in range(k):
        nxt = f"S{i + 1}" if i + 1 < k else None
        nodes = [call_node(f"c{i}", nxt)] if nxt else [delay_node(f"c{i}")]
        scripts.append({"id": f"S{i}", "name": f"脚本{i}", "nodes": nodes, "edges": []})
    f = flow(nodes=[call_node("n1", "S0")], scripts=scripts)
    errs = sg.validate_scripts(f)
    check("超上限被拒绝", any("嵌套层数过深" in e for e in errs), str(errs))
    g = sg.build_graph(f, f["scripts"])
    chain = sg.longest_chain(g)
    check("最长链长度 = 层数+1（含根）", len(chain) == k + 1, f"{len(chain)} vs {k + 1}")
    # 减到上限以内应当通过
    scripts2 = scripts[: sg.MAX_SCRIPT_DEPTH]
    scripts2[-1] = {"id": scripts2[-1]["id"], "name": scripts2[-1]["name"],
                    "nodes": [delay_node("last")], "edges": []}
    f2 = flow(nodes=[call_node("n1", "S0")], scripts=scripts2)
    check("上限以内通过", sg.validate_scripts(f2) == [], str(sg.validate_scripts(f2)))

    print("[10] would_create_cycle（编辑时拦截用）")
    g = {"__root__": ["A"], "A": ["B"], "B": ["C"], "C": ["D"], "D": []}
    check("这张图本身无环", sg.find_any_cycle(g) is None)
    check("准备加 A→A 会被拒并报 A→A", sg.would_create_cycle(g, "A", "A") == ["A", "A"])
    # 加 D→A：从 A 能走回 D（A→B→C→D），所以 D→A 会闭合成 D→A→B→C→D
    check("准备加 D→A 会环（闭合链完整）",
          sg.would_create_cycle(g, "D", "A") == ["D", "A", "B", "C", "D"])
    check("准备加 D→B 会环", sg.would_create_cycle(g, "D", "B") == ["D", "B", "C", "D"])
    check("没有环时返回 None", sg.would_create_cycle({"A": [], "B": []}, "A", "B") is None)
    check("空 id 返回 None", sg.would_create_cycle(g, "", "A") is None)

    print("[11] 结构损坏（validate_flow 的下游兜底）")
    check("scripts 不是对象 → 无条目", sg.normalize_scripts([1, 2]) == {})
    check("node 缺少 params 不崩", sg.collect_calls({"nodes": [{"id": "x", "type": "script_call"}]}) == [])
    check("flow 为 None 不崩", sg.validate_scripts(None) == ["流程必须是 JSON 对象"])

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + "；".join(FAILED))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
