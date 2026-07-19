# 双Skills协同工作流说明
# 如何将「竞品情报分析官」与「总会计师」无缝集成

## Agent 工作流架构图

```
用户问题
   │
   ▼
┌─────────────────────────────┐
│  Agent 意图理解（LLM）       │
│  判断属于：                   │
│  A. 内部财务问题 → 总会计师    │
│  B. 竞品分析问题 → 情报分析官  │
│  C. 综合问题 → 双Skills联动    │
└─────────────────────────────┘
   │
   ├──A──► 总会计师（4个工具）
   │        evaluate_order
   │        get_store_dashboard
   │        simulate_price_change
   │        simulate_delivery_strategy
   │
   ├──B──► 情报分析官（5个工具）
   │        map_competitor_sku
   │        compare_price_matrix
   │        reverse_engineer_strategy
   │        generate_counter_strategy
   │        detect_market_gap
   │
   └──C──► 双Skills联动流程：
            Step1: 情报官 → reverse_engineer_strategy（拆解竞品策略）
            Step2: 总会计师 → evaluate_order / simulate_price_change（计算我方跟价利润影响）
            Step3: 情报官 → generate_counter_strategy（输出攻/守/避三套方案）
            Step4: Agent 综合输出完整竞争应对报告
```

## 交接总结：您现在拥有的Agent体系

| 模块 | Skills名称 | 角色 | 核心能力 |
|------|-----------|------|---------|
| 内部 | 动态盈利决策引擎 | 总会计师/总风控官/总军师 | 成本核算、盈亏平衡、订单风控、定价模拟 |
| 外部 | 竞品情报分析引擎 | 情报分析官/战略参谋长 | 商品映射、价格比对、策略反推、应对方案 |
| 协同 | 双Skills联动 | 内外兼修的运营决策中枢 | "对手在做什么"+"我们的底线在哪"="我们该怎么做" |

## Agent 的配置步骤

### Step 1：合并 System Prompt
将两个 README_FOR_AGENT.md 合并为一个完整的系统指令，确保Agent同时具备"总会计师"和"情报分析官"双重人格。

### Step 2：合并 Tools
将两个 tool_schemas.json 的JSON数组合并为一个，注册到Agent的工具列表中（共9个工具）。

### Step 3：部署后端
将两个 core_logic.py 部署为API服务，Agent调用工具时实际执行这些代码。

### Step 4：数据准备
按照 data_collection_checklist.md 开始采集竞品数据。

### Step 5：测试验证
配置完成后，使用测试对话进行端到端验证。

## 测试对话示例

配置完成后，您可以这样测试：

> "帮我分析一下朝阳路上的XX便利店。我采集了他们的数据：起送价20元，满39减5、满69减12，可乐卖1.5元（月销500+），农夫山泉2元（月销380）。我们的可乐进价1.2元卖3元，农夫山泉进价1.0元卖2.5元。帮我做个全面分析，我们该怎么应对？"

Agent将会：
1. 调用 `reverse_engineer_strategy` 拆解竞品策略
2. 调用 `evaluate_order`（总会计师）计算我方跟价的利润影响
3. 调用 `generate_counter_strategy` 输出攻/守/避三套方案
4. 以"您的战略参谋长"身份输出一份完整的竞争应对报告
