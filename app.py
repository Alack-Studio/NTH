import streamlit as st
import pandas as pd
import math
from datetime import date, timedelta

# ==========================================
# 0. 全局配置与虚拟数据库初始化
# ==========================================
st.set_page_config(page_title="制造协同与订单追踪系统", page_icon="🏭", layout="wide", initial_sidebar_state="expanded")

# 1. 初始化【产品与产能】主数据 (新增)
if 'products' not in st.session_state:
    st.session_state.products = pd.DataFrame({
        "产品规格": ["漏电保护插头-标准款", "漏电保护插头-定制款", "精密冲压端子-B型"],
        "标准日产能": [200, 150, 1000],  # 件/天
        "包装缓冲天数": [1, 2, 1]       # 完工后到出货的缓冲
    })

# 2. 初始化【订单数据】(新增预计发货日)
if 'orders' not in st.session_state:
    st.session_state.orders = pd.DataFrame({
        "订单编号": ["ORD-202310-001", "ORD-202310-002"],
        "客户名称": ["华东科技集团", "北方工业设备"],
        "产品规格": ["漏电保护插头-标准款", "精密冲压端子-B型"],
        "订单数量": [1000, 5000],
        "已完工数": [200, 0],
        "承诺交期": [date.today() + timedelta(days=10), date.today() + timedelta(days=15)],
        "预计发货日": [date.today() + timedelta(days=5), None], # None 表示尚未排产
        "当前状态": ["生产中", "待备料"],
        "物流运单": ["", ""]
    })

# 3. 初始化【库存数据】
if 'inventory' not in st.session_state:
    st.session_state.inventory = pd.DataFrame({
        "物料编码": ["MAT-1001", "MAT-1002", "MAT-1003"],
        "物料名称": ["阻燃外壳组件", "高导电铜材", "标准包装纸箱"],
        "现存量": [5000, 2000, 10000],
        "预留量": [1000, 1500, 0],
        "安全库存": [500, 1000, 2000]
    })

# ==========================================
# 辅助函数：动态计算预计发货日 (ETA)
# ==========================================
def calculate_eta(product_name, remaining_qty):
    """根据产品产能和剩余数量，计算预计发货日期"""
    if remaining_qty <= 0:
        return date.today()
    
    # 获取产品主数据
    prod_info = st.session_state.products[st.session_state.products["产品规格"] == product_name].iloc[0]
    daily_cap = prod_info["标准日产能"]
    buffer_days = prod_info["包装缓冲天数"]
    
    # 计算需要生产的天数 (向上取整)
    production_days = math.ceil(remaining_qty / daily_cap)
    
    # 预计发货日 = 今天 + 生产天数 + 缓冲天数
    return date.today() + timedelta(days=production_days + buffer_days)

# ==========================================
# 1. 系统左侧导航栏
# ==========================================
st.sidebar.title("制造协同系统 v1.2")
st.sidebar.markdown("---")
menu = st.sidebar.radio(
    "功能模块导航", 
    [
        "1. 系统总览 (管理层)", 
        "2. 销售订单 (业务端)", 
        "3. 物料计划 (采购/PMC)", 
        "4. 仓储管理 (仓库端)", 
        "5. 生产执行 (制造端)", 
        "6. 发货登记 (物流端)",
        "⚙️ 基础数据 (产能/工艺)" # 新增模块
    ]
)

# ==========================================
# 2. 核心业务模块逻辑
# ==========================================

# --- 模块 1: 系统总览 ---
if menu == "1. 系统总览 (管理层)":
    st.header("系统运行总览")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("系统总订单数", len(st.session_state.orders))
    col2.metric("待备料订单", len(st.session_state.orders[st.session_state.orders["当前状态"] == "待备料"]))
    col3.metric("在制订单 (WIP)", len(st.session_state.orders[st.session_state.orders["当前状态"] == "生产中"]))
    col4.metric("待发货订单", len(st.session_state.orders[st.session_state.orders["当前状态"] == "待发货"]))
    
    st.divider()
    st.subheader("订单实时台账 (含 ETA 预测)")
    
    # 检查是否有延期风险 (预计发货日 > 承诺交期)
    df_display = st.session_state.orders.copy()
    def check_risk(row):
        if pd.isna(row["预计发货日"]) or row["当前状态"] in ["待发货", "已发货"]:
            return "🟢 正常"
        if row["预计发货日"] > row["承诺交期"]:
            return "🔴 延期风险"
        return "🟢 正常"
        
    df_display["交付风险"] = df_display.apply(check_risk, axis=1)
    
    # 调整列顺序，把 ETA 放前面
    cols = ["订单编号", "客户名称", "产品规格", "订单数量", "已完工数", "承诺交期", "预计发货日", "交付风险", "当前状态", "物流运单"]
    st.dataframe(df_display[cols], use_container_width=True)

# --- 模块 2: 销售订单 ---
elif menu == "2. 销售订单 (业务端)":
    st.header("销售订单管理")
    st.markdown("#### 新建客户订单")
    with st.form("new_order_form"):
        col1, col2 = st.columns(2)
        with col1:
            customer = st.text_input("客户名称/简称")
            product = st.selectbox("产品规格", st.session_state.products["产品规格"].tolist())
        with col2:
            qty = st.number_input("订单数量", min_value=1, step=100)
            deadline = st.date_input("客户要求交期")
            
        submitted = st.form_submit_button("保存并生成订单", type="primary")
        if submitted:
            new_order_id = f"ORD-{date.today().strftime('%Y%m')}-{len(st.session_state.orders)+1:03d}"
            new_row = pd.DataFrame([{
                "订单编号": new_order_id, "客户名称": customer, "产品规格": product,
                "订单数量": qty, "已完工数": 0, "承诺交期": deadline,
                "预计发货日": None, # 录入时未排产，暂无确切 ETA
                "当前状态": "待备料", "物流运单": ""
            }])
            st.session_state.orders = pd.concat([st.session_state.orders, new_row], ignore_index=True)
            st.success(f"系统提示：订单 {new_order_id} 录入成功，已流转至PMC计划。")

# --- 模块 3: 物料计划 (PMC) ---
elif menu == "3. 物料计划 (采购/PMC)":
    st.header("物料需求计划 (MRP) & 排产下达")
    
    pending_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "待备料"]
    st.dataframe(pending_orders[["订单编号", "产品规格", "订单数量", "承诺交期"]], use_container_width=True)
    
    st.divider()
    order_to_update = st.selectbox("选择已完成物料齐套校验的订单", pending_orders["订单编号"].tolist() if not pending_orders.empty else ["暂无待办任务"])
    if order_to_update != "暂无待办任务":
        if st.button("物料已齐套，下达生产 (自动计算初版 ETA)", type="primary"):
            # 获取订单信息计算初始 ETA
            idx = st.session_state.orders.index[st.session_state.orders["订单编号"] == order_to_update].tolist()[0]
            prod_name = st.session_state.orders.at[idx, "产品规格"]
            total_qty = st.session_state.orders.at[idx, "订单数量"]
            
            # 调用函数计算预计发货日
            initial_eta = calculate_eta(prod_name, total_qty)
            
            st.session_state.orders.at[idx, "预计发货日"] = initial_eta
            st.session_state.orders.at[idx, "当前状态"] = "生产中"
            
            st.success(f"操作成功：工单已下达至车间！系统测算预计发货日为：{initial_eta}")
            st.rerun()

# --- 模块 4: 仓储管理 (保持不变) ---
elif menu == "4. 仓储管理 (仓库端)":
    st.header("仓储与库存管理")
    inv_df = st.session_state.inventory.copy()
    inv_df["可用量"] = inv_df["现存量"] - inv_df["预留量"] - inv_df["安全库存"]
    st.dataframe(inv_df, use_container_width=True)

# --- 模块 5: 生产执行 (含动态 ETA 刷新) ---
elif menu == "5. 生产执行 (制造端)":
    st.header("生产进度汇报与动态排程")
    producing_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "生产中"]
    
    if producing_orders.empty:
        st.info("当前暂无在制工单。")
    else:
        selected_order = st.selectbox("选择汇报工单", producing_orders["订单编号"])
        order_info = producing_orders[producing_orders["订单编号"] == selected_order].iloc[0]
        
        # 提取产品标准日产能展示
        prod_standard = st.session_state.products[st.session_state.products["产品规格"] == order_info['产品规格']].iloc[0]
        
        st.markdown(f"**加工产品**: {order_info['产品规格']} (标准产能: {prod_standard['标准日产能']}件/天) &nbsp;&nbsp;|&nbsp;&nbsp; **当前预计发货日**: {order_info['预计发货日']}")
        st.progress(order_info['已完工数'] / order_info['订单数量'], text=f"进度: {order_info['已完工数']} / {order_info['订单数量']}")
        
        with st.form("production_report_form"):
            add_qty = st.number_input("本次汇报完工数量", min_value=0, step=10)
            
            if st.form_submit_button("提交产量并刷新 ETA", type="primary"):
                new_completed = order_info['已完工数'] + add_qty
                idx = st.session_state.orders.index[st.session_state.orders["订单编号"] == selected_order].tolist()[0]
                
                st.session_state.orders.at[idx, "已完工数"] = new_completed
                remaining = order_info['订单数量'] - new_completed
                
                if remaining <= 0:
                    st.session_state.orders.at[idx, "当前状态"] = "待发货"
                    st.success("该工单已达标完工，系统已自动流转至【待发货】节点！")
                else:
                    # 动态重新计算 ETA
                    new_eta = calculate_eta(order_info['产品规格'], remaining)
                    st.session_state.orders.at[idx, "预计发货日"] = new_eta
                    st.success(f"汇报成功！剩余 {remaining} 件。系统已将最新【预计发货日】修正为：{new_eta}")
                st.rerun()

# --- 模块 6: 发货登记 (保持不变) ---
elif menu == "6. 发货登记 (物流端)":
    st.header("物流出货管理")
    shipping_orders = st.session_state.orders[st.session_state.orders["当前状态"] == "待发货"]
    if not shipping_orders.empty:
        ship_order = st.selectbox("选择发货订单", shipping_orders["订单编号"])
        tracking_num = st.text_input("录入物流承运商及运单号")
        if st.button("确认发货出库", type="primary"):
            st.session_state.orders.loc[st.session_state.orders["订单编号"] == ship_order, "物流运单"] = tracking_num
            st.session_state.orders.loc[st.session_state.orders["订单编号"] == ship_order, "当前状态"] = "已发货"
            st.success("发货登记成功！")
            st.rerun()
    else:
        st.info("暂无待发货订单")

# --- 模块 7: 基础数据管理 (新增) ---
elif menu == "⚙️ 基础数据 (产能/工艺)":
    st.header("产品档案与产能基准维护")
    st.markdown("在此设定不同产品的标准生产速率。**此数据将直接决定全系统 ETA（预计发货日）的推算结果。**")
    
    # 支持在网页上直接编辑产能表
    edited_df = st.data_editor(st.session_state.products, num_rows="dynamic", use_container_width=True)
    
    if st.button("保存基础数据变更", type="primary"):
        st.session_state.products = edited_df
        st.success("产能基准已更新！后续系统在计算 ETA 时将采用最新速率。")
