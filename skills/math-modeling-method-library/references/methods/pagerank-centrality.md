# PageRank 中心性 (`pagerank-centrality`)

- **族/适用性：** 图论与网络；有向链接的重要性递归传递。
- **假设：** 边权相等，均匀 teleportation，悬挂节点质量均匀分配，`0<damping<1`。
- **输入/单位：** `nodes`,`edges=[u,v]` 为关系；`damping` 无量纲；`iterations` 为次数。
- **公式/参数：** `r_i=(1-d)/N+d(sum r_j/out_j+dangling/N)`，以 L1 残差停止。
- **规模：** `O(iter*(V+E))`；超大网络需稀疏实现。
- **依赖：** Python 标准库。
- **失败信号：** 分数和偏离 1、未收敛、排名对 damping/边定义敏感。
- **验证：** 非负归一、对称小图、多 damping 比较。
- **图表：** `evidence` 节点大小编码中心性；`diagnostic` 残差曲线。
- **论文写法：** 报告 damping、悬挂处理和误差；中心性不写成因果影响力。
- **来源边界：** NetworkX（BSD-3-Clause）只读参考；迭代实现原创。
