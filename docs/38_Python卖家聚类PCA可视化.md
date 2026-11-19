# 第 46 课 Python 卖家聚类 PCA 可视化

第 45 课的 K-Means 用三个标准化特征分组。本课用 PCA 把它们投影成二维坐标，观察各簇在图中的位置。图上的颜色和形状沿用 K=3、种子 42 的聚类标签。

在项目根目录的 PowerShell 运行下面的命令。

```powershell
.\.venv\Scripts\python.exe .\src\14_seller_clustering.py --pca
```

图片写到 `reports/sellers_v1/seller_clusters_pca.png`。如果环境提示缺少 Matplotlib，可用项目解释器安装验证版本。

```powershell
.\.venv\Scripts\python.exe -m pip install matplotlib==3.7.5
```

## Q30 读散点图和解释方差

每个点对应一位卖家。PCA 将标准化后的对数订单量、延迟率和低评分率线性组合成新的轴。PC1 捕捉最多的变异，PC2 捕捉与 PC1 正交的方向中最多的剩余变异。两项解释方差相加，表示图中两个方向保留了三列标准化特征总变异的多少。[scikit-learn PCA 文档](https://scikit-learn.org/1.3/modules/generated/sklearn.decomposition.PCA.html)

例如，如果累计解释方差是 80%，余下 20% 的变异就留在图中省略的方向。两个卖家在图上接近，也可能沿这个方向相隔较远。解读每簇的业务特点时，可以一起看 Q29 的原始订单量、延迟率和低评分率。

已运行默认命令和 `--pca`，两次的 K 值诊断与簇画像一致。导出的图覆盖全部 408 位入选卖家，轴标签上的解释方差与终端输出一致。

## 我的理解

1. PC1 和 PC2 各解释了多少变异？一起解释了多少？图中省略了多少？
2. 图上两个不同簇的点靠得很近时，为什么仍可能分在不同簇？K-Means 用的是哪三列特征？
