# 第 45 课 Python 卖家 K-Means 聚类

这次根据卖家的订单量和两种问题比率探索分组。每个卖家是一行。数据沿用 Q26 的单卖家已交付订单范围和最新有效评分规则。

在项目根目录的 PowerShell 运行下面的命令。使用第 40 课的项目虚拟环境和 scikit-learn 1.3.2。

```powershell
.\.venv\Scripts\python.exe .\src\14_seller_clustering.py
```

## Q29 比较 K 值和簇的特点

两个比率的分母各至少 50 笔才纳入聚类，沿用 Q27 的样本门槛。K-Means 使用三个特征。订单量先做 `log1p`，减小右偏分布中头部卖家与其他卖家的数量级差距。延迟率和低评分率保留原始比例。随后用 `StandardScaler` 把三列转换为标准分数，再按距离聚类。[scikit-learn KMeans 文档](https://scikit-learn.org/1.3/modules/generated/sklearn.cluster.KMeans.html)

| 诊断列 | 含义 |
| --- | --- |
| `k` | 簇数，本课比较 2 至 5 |
| `silhouette` | 种子 42 的轮廓系数，越高表示这组特征下簇内聚合和簇间分离越明显 |
| `min_seed_ari` | 种子 7 和 2026 各自与种子 42 的调整兰德指数（ARI），取较小值。1 表示分组完全一致，即使簇编号不同 |
| `smallest_cluster` | 种子 42 的结果中最小簇的卖家数 |

ARI 在这里衡量同一批数据换初始化种子后的分组一致性。每个种子运行 20 次初始化，保留该种子下簇内平方距离之和最小的一次。[轮廓系数](https://scikit-learn.org/1.3/modules/generated/sklearn.metrics.silhouette_score.html) · [调整兰德指数](https://scikit-learn.org/1.3/modules/generated/sklearn.metrics.adjusted_rand_score.html)

第二张表固定用 **K=3、种子 42** 练习解读。簇编号只是标签。用 `sellers` 和 `median_orders` 看簇的卖家数和典型规模。簇内的延迟率和低评分率用相应订单数加总后相除。聚类时每位卖家作为一个点，汇总比率时每笔符合该指标口径的订单等权。

脚本已在项目虚拟环境中运行，2,925 位卖家的聚类前计数与 Q26 的 MySQL 全量结果逐行一致。当前 Windows 验证环境出现 joblib 的物理核心数探测提示，程序改用逻辑核心数完成了计算。

## 我的理解

1. 有多少位卖家达到聚类样本门槛？哪个 K 的轮廓系数最高？同一行的 `min_seed_ari` 和最小簇卖家数分别是多少？
2. 看 K=3 的画像表。哪个簇的低评分率最高？它有多少位卖家、多少笔订单？这个簇的典型订单量和另外两簇相比如何？
