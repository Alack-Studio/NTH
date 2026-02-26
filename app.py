import streamlit as st
import pandas as pd
from datetime import date, timedelta

# ==========================================
# 0. 全局配置与虚拟数据库初始化
# ==========================================
st.set_page_config(page_title="制造协同与订单追踪系统", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")

# 初始化订单数据
if 'orders' not in st.session_state:
    st.session_state.orders = pd.DataFrame({
        "订单编号": ["ORD-202310-001", "ORD-202310-002"],
        "客户名称": ["华东科技集团", "北方工业设备"],
        "产品规格": ["漏电保护插头-标准款", "精密冲压端子-B型"],
        "订单数量": [1000, 5000],
        "已完工数": [200, 0],
        "承诺交期": [date.today() + timedelta(days=10), date.today() + timedelta(days=15)],
        "当前状态": ["生产中", "待备料"],
        "物流运单": ["", ""]
    })

# 初始化库存数据 (新增模块)
if 'inventory' not in st.session_state:
    st.session_state.inventory = pd.DataFrame({
        "物料编码": ["MAT-1001", "MAT-1002", "MAT-1003"],
        "物料名称": ["阻燃外壳组件", "高导电铜材", "标准包装纸箱"],
        "现存量": [5000, 2000, 10000],
        "预留量": [1000, 1500, 0],
        "安全库存": [500, 1000, 2000]
    })

# ==========================================
# 1. 系统左侧导航栏
# ==========================================
st.sidebar.title("制造协同系统 v1.1")
st.sidebar.markdown("---")
menu = st.sidebar.radio(
    "功能模块导航", 
    [
        "1. 系统总览 (管理层)", 
        "2. 销售订单 (业务端)", 
        "3. 物料计划 (采购/PMC)", 
        "4. 仓储管理 (仓库端)", 
        "5. 生产执行 (制造端)", 
        "6. 发货登记 (物流端)"
    ]
)

# ==========================================
# 2. 核心业务模块逻辑
# ==========================================

# --- 模块 1: 系统总览 ---
if menu == "1. 系统总览 (管理层)":
    st.header("系统运行总览")
    st.markdown("实时监控订单流转与生产核心指标")
    
    # 顶部数据卡片
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("系统总订单数", len(st.session_state.orders))
    col2.metric("待备料订单", len(st.session_state.orders[st.session_state.orders["当前状态"] == "待备料"]))
    col3.metric("在制订单 (WIP)", len(st.session_state.orders[st.session_state.orders["当前状态"] == "生产中"]))
    col4.metric("待发货订单", len(st.session_state.orders[st.session_state.orders["当前状态"] == "待发货"]))
    
    st.divider()
    st.subheader("订单实时台账")
    st.dataframe(st.session_state.orders, use_container_width=True)

# --- 模块 2: 销售订单 ---
elif menu == "2. 销售订单 (业务端)":
    st.header("销售订单管理")
    
    tab1, tab2 = st.tabs(["录入新订单", "订单明细查询"])
    
    with tab1:
        st.markdown("#### 新建客户订单")
        with st.form("new_order_form"):
            col1, col2 = st.columns(2)
            with col1:
                customer = st.text_input("客户名称/简称")
                product = st.selectbox("产品规格", ["漏电保护插头-标准款", "漏电保护插头-定制款", "精密冲压端子-B型"])
            with col2:
                qty = st.number_input("订单数量", min_value=1, step=100)
                deadline = st.date_input("客户要求交期")
                
            submitted = st.form_submit_button("保存并生成订单", type="primary")
            if submitted:
                new_order_id = f"ORD-{date.today().strftime('%Y%m')}-{len(st.session_state.orders)+1:03d}"
                new_row = pd.DataFrame([{
                    "订单编号": new_order_id, "客户名称": customer, "产品规格": product,
                    "订单数量": qty, "已完工数": 0, "承诺交期": deadline,
                    "当前状态": "待备料", "物流运单": ""
                }])
                st.session_state.orders = pd.concat([st.session_state.orders, new_row], ignore_index=True)
                st.success(f"系统提示：订单 {new_order_id} 录入成功，已流转至PMC计划。")
    
    with tab2:
        st.dataframe(st.session_state.orders, use_container_width=True)

# --- 模块 3: 物料计划 ---
elif menu == "3. 物料计划 (采购/PMC)":
    st.header("物料需求计划 (MRP)")
    st.info("说明：第一阶段支持系统自动归集待备料订单，BOM分解暂由人工线下确认后更新状态。")
    
    pending_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "待备料"]
    st.subheader("待分析订单池")
    st.dataframe(pending_orders[["订单编号", "产品规格", "订单数量", "承诺交期"]], use_container_width=True)
    
    st.divider()
    st.subheader("状态推进控制")
    order_to_update = st.selectbox("选择已完成物料齐套校验的订单", pending_orders["订单编号"].tolist() if not pending_orders.empty else ["暂无待办任务"])
    if order_to_update != "暂无待办任务":
        if st.button("物料已齐套，下达生产", type="primary"):
            st.session_state.orders.loc[st.session_state.orders["订单编号"] == order_to_update, "当前状态"] = "生产中"
            st.success("操作成功：工单已下达至车间！")
            st.rerun()

# --- 模块 4: 仓储管理 (新增核心模块) ---
elif menu == "4. 仓储管理 (仓库端)":
    st.header("仓储与库存管理")
    
    # 根据公式计算可用量：可用量 = 现存 - 预留 - 安全库存
    inv_df = st.session_state.inventory.copy()
    inv_df["可用量"] = inv_df["现存量"] - inv_df["预留量"] - inv_df["安全库存"]
    # 防止可用量显示为负数造成误解（虽然逻辑上可能欠料）
    inv_df["库存健康度"] = inv_df["可用量"].apply(lambda x: "🔴 缺口" if x < 0 else "🟢 充足")
    
    tab1, tab2 = st.tabs(["实时库存台账", "库存变更作业 (入/出/盘)"])
    
    with tab1:
        st.markdown("#### 综合库存视图")
        st.dataframe(inv_df, use_container_width=True)
        
    with tab2:
        st.markdown("#### 库存单据录入")
        with st.form("inventory_adj_form"):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                mat_code = st.selectbox("选择操作物料", inv_df["物料编码"].tolist())
            with col_b:
                adj_type = st.selectbox("业务类型", ["采购入库", "生产领料 (出库)", "盘点调整"])
            with col_c:
                adj_qty = st.number_input("操作数量", min_value=1, step=100)
                
            adj_submit = st.form_submit_button("确认提交单据", type="primary")
            if adj_submit:
                current_stock = st.session_state.inventory.loc[st.session_state.inventory["物料编码"] == mat_code, "现存量"].values[0]
                
                if adj_type == "采购入库" or adj_type == "盘点调整": # 简单起见，盘点默认增加，实际可分盈亏
                    new_stock = current_stock + adj_qty
                else: # 生产领料出库
                    new_stock = current_stock - adj_qty
                    
                st.session_state.inventory.loc[st.session_state.inventory["物料编码"] == mat_code, "现存量"] = new_stock
                st.success(f"操作成功！{mat_code} 的现存量已更新为：{new_stock}")
                st.rerun()

# --- 模块 5: 生产执行 ---
elif menu == "5. 生产执行 (制造端)":
    st.header("生产进度汇报 (SFC)")
    producing_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "生产中"]
    
    if producing_orders.empty:
        st.info("当前暂无在制工单。")
    else:
        selected_order = st.selectbox("选择汇报工单", producing_orders["订单编号"])
        order_info = producing_orders[producing_orders["订单编号"] == selected_order].iloc[0]
        
        st.markdown(f"**加工产品**: {order_info['产品规格']} &nbsp;&nbsp;|&nbsp;&nbsp; **目标产量**: {order_info['订单数量']} &nbsp;&nbsp;|&nbsp;&nbsp; **累计已完工**: {order_info['已完工数']}")
        
        with st.form("production_report_form"):
            add_qty = st.number_input("本次汇报完工数量", min_value=0, step=10)
            daily_capacity = st.number_input("标准日产能评估基准 (件/天)", value=200)
            
            if st.form_submit_button("提交产量汇报", type="primary"):
                new_completed = order_info['已完工数'] + add_qty
                st.session_state.orders.loc[st.session_state.orders["订单编号"] == selected_order, "已完工数"] = new_completed
                
                remaining = order_info['订单数量'] - new_completed
                if remaining <= 0:
                    st.session_state.orders.loc[st.session_state.orders["订单编号"] == selected_order, "当前状态"] = "待发货"
                    st.success("该工单已达标完工，系统已自动流转至【待发货】节点！")
                else:
                    eta_days = (remaining // daily_capacity) + (1 if remaining % daily_capacity > 0 else 0)
                    st.success(f"汇报成功！剩余 {remaining} 件。基于当前产能基准，预计仍需 {eta_days} 天完工。")
                st.rerun()

# --- 模块 6: 发货登记 ---
elif menu == "6. 发货登记 (物流端)":
    st.header("物流出货管理")
    shipping_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "待发货"]
    
    if shipping_orders.empty:
        st.info("当前暂无待发货单据。")
    else:
        ship_order = st.selectbox("选择发货订单", shipping_orders["订单编号"])
        tracking_num = st.text_input("录入物流承运商及运单号", placeholder="例如：顺丰速运 SF123456789")
        
        if st.button("确认发货出库", type="primary"):
            if tracking_num:
                st.session_state.orders.loc[st.session_state.orders["订单编号"] == ship_order, "物流运单"] = tracking_num
                st.session_state.orders.loc[st.session_state.orders["订单编号"] == ship_order, "当前状态"] = "已发货"
                st.success(f"系统记录成功！单据状态变更为：已发货。运单号：{tracking_num}")
                st.rerun()
            else:
                st.error("操作阻断：必须录入有效运单号才能执行发货。")
