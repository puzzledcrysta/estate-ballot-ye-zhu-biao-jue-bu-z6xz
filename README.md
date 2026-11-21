# 业主表决簿

住宅小区业委会计票员可用本地工作台处理表决议案，复查户与面积双计并与独立清单逐笔核对。

同一所有权主体跨房合并为一票，按共有比例计算面积；参与和赞成均同时满足面积及人数门槛。

## 启动

```sh
docker compose up --build
```

打开 http://127.0.0.1:18305 并运行随附样例。可以在「导入来源与外部账」上传自己的 CSV，也可以编辑表单中的样例。数据保存于 Compose 卷 `ledger`。使用 `APP_PORT` 可覆盖宿主端口。

## 工作步骤

1. 检查「送审票册」与「产权字段」，定位导入坏行与字段归一结果。
2. 在「冲突票夹」区分冲突、业务拒绝、重传与旧版本。
3. 打开「份额计票」并点击任意记录的「查看依据」。
4. 在「公示勾稽」检查金额或用量差异。通过「议案记录」复算原文件，通过「计票底稿」提交意见并下载证据。

接口定义见 `/openapi.json`。字段、允许区间及算例见 [数据字典](docs/DATA-DICTIONARY.md)，模块和回归测试见 [测试登记](docs/DEPTH.md)。

## 验证

```sh
docker compose config --quiet
docker compose exec -T app pytest -q
```

`sample_data/shift.csv` 是班次数据，`sample_data/external.csv` 是独立账样例。`cases.csv` 固定业务反例，`legacy.csv` 和 `truncated.csv` 用于验证历史格式与断行。
