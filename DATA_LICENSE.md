# 数据来源与派生结果许可

数据名称为 **Brazilian E-Commerce Public Dataset by Olist**，提供者为 Olist 及该数据页列出的协作者。

- 来源：[Olist Kaggle 数据页](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)。
- 来源页许可：[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-nc-sa/4.0/)。
- 许可核对日期：2026-11-19。

本项目保留来源署名。`data/processed/`、`powerbi/Olist/data/` 及基于该数据导出的结果、图表和报表属于本项目对源数据的清洗、聚合和分析产物，继续按数据来源的 CC BY-NC-SA 4.0 要求分发和使用。根目录 MIT 许可只覆盖本项目原创代码，不重新许可 Olist 数据，也不授予原数据的商业使用权限。使用者应保留署名、说明修改、遵守非商业用途与相同方式共享条款，具体以链接中的许可全文为准。

本项目所做的修改包括类型转换、质量标记、整数分金额、日期资格、评价取值、订单或客户汇总、地理代表点、统计分析与报表展示。原始 CSV 没有随交付包再次分发，可从来源页取得；现有数据包含源数据已匿名化的客户和卖家标识、邮编地理信息与评价内容。

对 scikit-learn、Pandas、PyArrow 等依赖及 Microsoft 文件格式规范的使用不改变这些第三方内容自身的许可。构建工具下载的验证依赖和参考缓存不包含在发布包中。
