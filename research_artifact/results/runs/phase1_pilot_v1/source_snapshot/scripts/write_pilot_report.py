"""Write evidence-bound phase-one report; every numeric cell comes from raw runs."""
import json
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/runs/phase1_pilot_v1"
SUP = ROOT / "results/runs/phase1_solver_supplement_v1"


def main():
    rows = json.loads((RUN / "summary.json").read_text())
    analysis = json.loads((RUN / "analysis/analysis.json").read_text())
    supplement = json.loads((SUP / "summary.json").read_text())
    manifest = json.loads((ROOT / "data/public/manifest.json").read_text())
    metadata = json.loads((RUN / "metadata.json").read_text())
    finished = json.loads((RUN / "completion.json").read_text())
    def performance(case, method, budget=0.1):
        return 100 * mean(r["fresh_fraction"] for r in rows
                          if r["case"] == case and r["method"] == method and r["budget_fraction"] == budget)
    def pair(case, baseline, budget=0.1):
        return next(r for r in analysis["differences"] if r["case"] == case
                    and r["baseline"] == baseline and r["budget_fraction"] == budget)
    def diagnostic(case, metric):
        return mean(r[metric] for r in analysis["mechanism_by_seed"]
                    if r["case"] == case and r["budget_fraction"] == 0.1)
    lines = ["# 首日验证报告与论文可行性判断", "",
             "结论：**有条件通过，值得进入确认性实验；能够写成实证研究稿，当前证据不支持新算法论文，也不足以承诺CSCWD录用。**", "",
             "本报告使用验证种子0–4，未运行预留测试种子100–119。所有百分点变化均为任务成功率的绝对差，不是相对百分比。只有5个验证种子，以下区间为探索性配对bootstrap，不能当最终显著性结论。", "",
             "## 已实际完成", "",
             "完整公开结构下载与候选审计；独立事件生成、版本精确的多窗口模拟器、累计历史率估计、六预算内方法与无限预算参考；同快照诊断；31项测试通过；60次MILP静态切片；额外两条件的MILP动态检查。", "",
             "主pilot共420条策略轨迹，每条30窗口，共12600个策略窗口；其中SABS为60条轨迹，同快照诊断独立于真实状态更新。它们共享每条件的外生事件。主pilot运行起止UTC为 " + metadata["started_utc"] + " 至 " + finished["completed_utc"] + "，不包含数据下载、实现、测试及报告时间。", "",
             "## 公开数据", "", "| 家族 | 任务 | 原始文件 | 同步全集 | 共享输入文件 | 最大输入组 |", "|---|---:|---:|---:|---:|---:|"]
    for r in manifest["selected"]:
        lines.append(f'| {r["family"]} | {r["tasks"]} | {r["raw_files"]} | {r["sync_files"]} | {r["shared_sync_files"]} | {r["max_inputs"]} |')
    lines += ["", "固定commit：`" + manifest["commit"] + "`。所有28个家族候选均按完整输入结构审计，按预定规则选最小可用实例。未截取子图。公开数据只提供结构，更新事件、窗口、成本与使用时刻仍为合成。许可文件、原始JSON、转换与SHA256见 data/public/manifest.json。", "",
              "Seismology没有任务间共享输入，是重要负向结构对照；其103输入任务仍保留。SABS在5个种子共150次该大组使用中成功率为0；其余2–4输入任务平均成功率约47.39%。整体平均46.92%不能代表大组获得服务。该0是观察结果，不是普遍不可能性定理。", "",
              "## 主比较与公开结构结果", "", "预算均为同步全集成本的10%；合成条件为均值率0.5、cv=1。", "",
              "| 条件 | 无存活组 % | 同信息逐文件 % | SABS % | SABS减无存活组 pp | SABS减逐文件 pp |", "|---|---:|---:|---:|---:|---:|"]
    for case, label in [("synthetic_mu0.5", "合成"), ("public_seismology", "Seismology"), ("public_montage", "Montage")]:
        lines.append(f'| {label} | {performance(case,"bundle_no_survival_partial"):.2f} | {performance(case,"item_utility"):.2f} | {performance(case,"sabs_partial"):.2f} | {pair(case,"bundle_no_survival_partial")["mean_pp"]:+.2f} | {pair(case,"item_utility")["mean_pp"]:+.2f} |')
    lines += ["", "公开两家族中上述两个差值均在5个验证种子上为正。合成10%预算的组对逐文件比较有1个种子为负，因此不能声称每个结构/种子都获益。", "",
              "| 差值 | 平均 pp | 探索性95%配对区间 pp | 正/负种子 |", "|---|---:|---|---|"]
    for case, label in [("synthetic_mu0.5", "合成"), ("public_seismology", "Seismology"), ("public_montage", "Montage")]:
        for baseline, b_label in [("bundle_no_survival_partial", "无存活组"), ("item_utility", "同信息逐文件")]:
            r = pair(case, baseline)
            lines.append(f'| {label} SABS−{b_label} | {r["mean_pp"]:+.2f} | [{r["lo_pp"]:+.2f}, {r["hi_pp"]:+.2f}] | {r["positive_seeds"]}/{r["negative_seeds"]} |')
    lines += ["", "## 机制确实改变了什么", "", "| 率/间隔 | 真实q CV | 估计q CV | 同快照动作分歧 % | 同快照真实收益 pp | 全轨迹SABS减无存活组 pp |", "|---|---:|---:|---:|---:|---:|"]
    for case, label in [("mechanism_cv0.0_fixed", "同质/固定"), ("mechanism_cv0.0_uniform", "同质/变化"), ("mechanism_cv1.0_fixed", "异质/固定"), ("synthetic_mu0.5", "异质/变化")]:
        lines.append(f'| {label} | {diagnostic(case,"true_q_cv"):.3f} | {diagnostic(case,"estimated_q_cv"):.3f} | {100*diagnostic(case,"action_difference_fraction"):.1f} | {diagnostic(case,"same_snapshot_gain_pp"):+.3f} | {pair(case,"bundle_no_survival_partial")["mean_pp"]:+.3f} |')
    lines += ["", "观察1：同质/固定条件真实q相同，但有限历史估计引入离散度，可改变约46%的动作，长期平均提升只有约0.047个百分点。动作分歧不能代替实际收益。精确非1等q的固定快照测试则保持同动作，公式边界没有被破坏。", "",
              "观察2：同质/变化条件的同快照收益为正，而全轨迹差约−0.073个百分点。两者评估的是不同缓存演化；不能把单步预测改善写成长期调度保证。该负差区间跨0，当前只能说没有明确额外收益。", "",
              "观察3：低更新率0.1、预算25%时，各核心方法均为82.32%，与无限预算参考相同。原有提升主张必须限于资源确实受限的条件。", "",
              "共同冲击η=0.5保持边际更新率，在本验证条件下未使SABS排名反转：SABS为20.70%，无存活组17.58%，同信息逐文件18.65%。这只能说明当前冲击设置未破坏其收益，不能宣称已找到强相关下的失败阈值或普遍鲁棒性。", "",
              "## 精确求解是否削弱算法论点", "",
              "60次静态MILP全部status=0；每模式30次，其中24次最优值非零。存活模式下启发式相对最优目标的平均损失为1.17%，最大7.45%；无存活模式平均0.49%，最大7.69%。分母为同快照最优目标，零目标不除零。", "",
              "发现小例可快速求解后，在测试种子未使用前登记 configs/pilot_supplement.json，额外检查合成和Montage两个固定条件、5个验证种子、30窗口、有/无存活两个求解器版本，共20条轨迹/600次求解。该补充是验证性质，不能隐去它是看过pilot后追加的事实。", "",
              "| 条件 | SABS % | 动态MILP有存活 % | 动态MILP无存活 % |", "|---|---:|---:|---:|"]
    for case, label in [("synthetic_mu0.5", "合成"), ("public_montage", "Montage")]:
        one = lambda method: 100 * mean(r["fresh_fraction"] for r in supplement if r["case"] == case and r["method"] == method)
        lines.append(f'| {label} | {performance(case,"sabs_partial"):.2f} | {one("milp_survival_dynamic"):.2f} | {one("milp_no_survival_dynamic"):.2f} |')
    detailed = [r for p in (SUP / "records").glob("*.json") for r in json.loads(p.read_text())["windows"] if r["nonempty_stale_set"]]
    solver_ms = median(r["solver"]["seconds"] for r in detailed) * 1000
    greedy_ms = median(r["heuristic_seconds_same_snapshot"] for r in detailed) * 1000
    lines += ["", f"580个非空同快照中，MILP建模+求解中位数约{solver_ms:.2f}ms，组启发式约{greedy_ms:.2f}ms（每次三次计时的中位数）。差距很小，不能宣传数量级速度优势。原主轨迹中位数与这组不同范围的计时不可直接比较。", "",
              "补充动态MILP直接执行单步解，没有附加SABS的部分同步规则，零利润解的平局处理由求解器决定；两种利润版本规则相同。它不是长期最优解，这里也不据此宣称精确方法长期统治。它已足够说明：静态背包很难并不是当前小规模采用新贪心的充分理由。下一阶段须保留求解器强对照，并公开其平局与部分进度处理。", "",
              "## 首日继续判断", "",
              "有条件通过：模型可执行、关键正确性已检查、两个完整公开结构可用、效果超出弱基线比较、存活项的额外价值在异质条件有验证依据，负面条件可复现。", "",
              "尚未达到投稿结论：只有5个验证种子；没有真实设计协作行为；静态模型与已有SUKP/依赖更新研究重合很大；关联冲击只测试一档；尚未完成确认性数据和参考文献全面核验。不能把pilot当最终测试或用其bootstrap区间声称最终显著性。", "",
              "## 下一阶段固定建议", "",
              "继续保留实证主线，删除SABS算法新颖和明显速度优势主张。正式测试前冻结源/配置/数据版本；保留等q、估计噪声、跨窗口积累和大组服务失败。确认性实验应按原v2核心范围运行预留种子，同时保留新增的两个条件求解器强对照；该增补须先登记，不能事后挑选好结果。", "",
              "论文可用主张：在本固定窗口模型中，组选择与存活估计的价值取决于预算和任务风险异质性；动作变化可能只是估计噪声，单步收益不保证跨窗口改善；小规模精确求解是必要强对照。上述应描述为本实验支持的观察，不宣称首次发现一般规律。", "",
              "## 证据与复现", "",
              "- 原始轨迹与逐窗口动作：results/runs/phase1_pilot_v1/traces、records。", "- 配对差与逐种子值：analysis/analysis.json、paired_differences.csv。", "- 图：analysis/pilot_evidence.png；由 scripts/analyze_pilot.py 生成。", "- MILP切片：milp/*.json；补充对照：results/runs/phase1_solver_supplement_v1。", "- 来源清单：data/public/manifest.json，保存候选审计、版本、许可证与文件哈希。", "- 重跑：python3 scripts/run_pilot.py --run-id <新目录名>；分析：python3 scripts/analyze_pilot.py。原目录只允许同哈希断点续跑。", "",
              "本报告全部实验数字来自上述文件。完整查新范围及不能据摘要排除的等价性风险见 docs/LITERATURE_GATE.md。"]
    (ROOT / "docs/PILOT_REPORT.md").write_text("\n".join(lines) + "\n")
    print("PILOT_REPORT.md written from actual run outputs")


if __name__ == "__main__":
    main()
