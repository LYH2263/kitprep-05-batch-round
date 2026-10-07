# KitPrep 中央厨房 BOM 备料

按菜品 BOM 展开订单行、合并同原料需求，对照库存计算缺料并生成备料单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5000 |
| API | http://localhost:10100 |
| API 文档 | http://localhost:10100/docs |
| Postgres | localhost:5451 |

健康检查：`GET http://localhost:10100/api/health`

## 使用说明

1. 在「菜品」「BOM」维护中央厨房出品与用料树。
2. 在「订单」「库存」确认当日需求与现有库存。
3. 在「库存」为原料配置**起备倍数**(留空 = 不取整;必须为正数):
   - 保存倍数只改栏位,同时把每个订单**正在用的那张备料单**(最新一张)整张按新倍数取整重写占用列与缺料贴;已经落下的旧单不动。
   - 取整口径:需求四舍五入到倍数的整数倍;取整为 0 的行保留、占量为 0。
   - 倍数为 0 或负数会被拒绝,栏、单、缺料贴全部保持写入前状态。
   - 保存倍数不改库存结存。
4. 打开「备料单」查看已落单的备料表(需求 / 占用 / 库存 / 缺料);点「生成备料单」只出新单,不动库存。
5. 在「缺料」查看 占用 − 库存 为正的原料,与备料台、占用列同一口径。

## 开发与测试

```bash
docker compose exec api pytest -q
```
